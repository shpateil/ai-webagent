"""веб-агент. fastapi: авторизация, чаты, sse-стрим агента"""
import asyncio
import hmac
import json
import logging
import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

import memory
import vision
from agent import stream_turn
from config import (
    COOKIE_DAYS,
    COOKIE_NAME,
    COOKIE_SECRET,
    HISTORY_LIMIT,
    LOGIN,
    PASSWORD,
    STATIC_DIR,
    UPLOAD_DIR,
)
from tools import ATTACH_DIR

from memory import ensure_owner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

def _body(data):
    """тело запроса как словарь: битый json, null и список не роняют роут"""
    return data if isinstance(data, dict) else {}


async def _json(request: Request) -> dict:
    try:
        return _body(await request.json())
    except Exception:
        return {}


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
if not COOKIE_SECRET or not PASSWORD:
    raise RuntimeError("AI_COOKIE_SECRET и AI_PASSWORD обязательны")
signer = URLSafeTimedSerializer(COOKIE_SECRET, salt="ai-session")

MAX_UPLOAD = 64 * 1024 * 1024
_login_fails = {}

try:
    ensure_owner(LOGIN or "shpateil", PASSWORD or "", "шпатель")
except Exception as _e:
    log.warning("владелец не создан: %s", _e)

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif", ".avif", ".tif", ".tiff"}


def _is_image(data: bytes, ctype: str, name: str) -> bool:
    """картинка или нет. телефоны часто шлют application/octet-stream,
    поэтому верим расширению и первым байтам, а не только mime от браузера"""
    ext = Path(name).suffix.lower()
    if ext in IMG_EXT:
        return True
    if ctype.startswith("image/"):
        return True
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):            # jpeg
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):      # png
        return True
    if head.startswith(b"GIF8"):                   # gif
        return True
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if head[:2] == b"BM":                          # bmp
        return True
    if head[4:8] in (b"ftyp",) and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"avif"):
        return True
    if head[:4] in (b"II*\x00", b"MM\x00*"):         # tiff
        return True
    return False



def make_cookie(uid, back=0):
    """uid — от чьего имени работаем, back — под кем были до переключения (только для владельца)"""
    return signer.dumps({"uid": int(uid), "back": int(back or 0)})


def check_cookie(token):
    try:
        data = signer.loads(token, max_age=COOKIE_DAYS * 86400)
        return int(data.get("uid") or 0)
    except BadSignature:
        return 0
    except Exception:
        return 0


def cookie_data(token):
    try:
        return signer.loads(token, max_age=COOKIE_DAYS * 86400) or {}
    except Exception:
        return {}


async def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    d = cookie_data(token) if token else {}
    uid = int(d.get("uid") or 0)
    if uid:
        u = memory.user_by_id(uid)
        if u and not u.get("disabled"):
            # обратный путь: только если под нами действительно был владелец
            back = int(d.get("back") or 0)
            if back and back != uid:
                b = memory.user_by_id(back)
                if b and b.get("is_owner") and not b.get("disabled"):
                    u = dict(u)
                    u["impersonated"] = 1
                    u["back_login"] = b["login"]
            return u
    raise HTTPException(status_code=401, detail="не авторизован")


async def admin_user(user: dict = Depends(current_user)):
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="только владелец")
    return user


@app.post("/api/login")
async def login(request: Request):
    body = await _json(request)
    now = time.time()
    login_name = str(body.get("login", "")).strip()
    pw = str(body.get("password", ""))
    # блокируем по логину: иначе один человек с ошибками запирает вход всем
    key = "u:" + login_name.lower()
    fails, until = _login_fails.get(key, (0, 0))
    if until and now < until and fails >= 5:
        left = int(until - now) + 1
        return JSONResponse({"error": f"слишком много попыток, подожди {left} с"}, status_code=429)
    u = memory.user_by_login(login_name)
    ok = bool(u) and not u.get("disabled") and memory.verify_password(pw, u["phash"])
    if not ok:
        fails += 1
        _login_fails[key] = (fails, now + min(fails * 5, 120) if fails >= 5 else 0)
        return JSONResponse({"error": "неверный логин или пароль"}, status_code=401)
    _login_fails.pop(key, None)
    ip = request.client.host if request.client else "?"
    resp = JSONResponse({"ok": True, "user": u["login"], "owner": bool(u["is_owner"])})
    resp.set_cookie(COOKIE_NAME, make_cookie(u["id"]), max_age=COOKIE_DAYS * 86400,
                    httponly=True, secure=True, samesite="lax", path="/")
    log.info("вход %s с %s", u["login"], ip)
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
async def me(user: dict = Depends(current_user)):
    return {"user": user["login"], "name": user.get("pname") or user["login"],
            "owner": bool(user.get("is_owner")), "web": bool(user.get("web", 1)),
            "mode": memory.user_mode(user["id"]),
            "model": memory.user_model(user["id"]),
            "impersonated": bool(user.get("impersonated")),
            "back": user.get("back_login") or ""}



def _own_chat(cid: int, user: dict):
    """чат должен принадлежать этому юзеру, иначе не существует"""
    o = memory.chat_owner(cid)
    if o != user["id"]:
        raise HTTPException(404, "нет чата")
    return True


@app.get("/api/chats")
async def chats(user: dict = Depends(current_user)):
    return {"chats": memory.list_chats(uid=user["id"])}


@app.post("/api/chats")
async def new_chat(user: dict = Depends(current_user)):
    """черновой чат: в базу не пишем, реально создастся при первом сообщении"""
    return {"id": 0}


@app.patch("/api/chats/{cid}")
async def patch_chat(cid: int, request: Request, user: dict = Depends(current_user)):
    _own_chat(cid, user)
    body = await _json(request)
    if body.get("title"):
        memory.rename_chat(cid, str(body["title"]))
    return {"ok": True}


@app.delete("/api/chats/{cid}")
async def del_chat(cid: int, user: dict = Depends(current_user)):
    _own_chat(cid, user)
    memory.delete_chat(cid)
    return {"ok": True}


@app.post("/api/me/model")
async def my_model(request: Request, user: dict = Depends(current_user)):
    from agent import norm_model
    body = await _json(request)
    memory.set_user_model(user["id"], norm_model(body.get("model")))
    return {"ok": True, "model": memory.user_model(user["id"])}


@app.get("/api/models")
async def models_list(user: dict = Depends(current_user)):
    from agent import MODES, MODELS
    return {"models": MODELS,
            "modes": {k: {"label": v["label"], "hint": v["hint"], "model": v["model"]}
                      for k, v in MODES.items()}}


@app.post("/api/me/mode")
async def my_mode(request: Request, user: dict = Depends(current_user)):
    from agent import norm_mode
    body = await _json(request)
    memory.set_user_mode(user["id"], norm_mode(body.get("mode")))
    return {"ok": True, "mode": memory.user_mode(user["id"])}


@app.post("/api/chats/{cid}/mode")
async def set_mode(cid: int, request: Request, user: dict = Depends(current_user)):
    _own_chat(cid, user)
    from agent import norm_mode
    body = await _json(request)
    memory.set_chat_mode(cid, norm_mode(body.get("mode")))
    return {"ok": True}


MAX_CID = 2 ** 62


@app.get("/api/chats/{cid}/messages")
async def chat_messages(cid: int, user: dict = Depends(current_user)):
    if not 0 < cid < MAX_CID:
        raise HTTPException(404, "нет чата")
    _own_chat(cid, user)
    rows = memory.messages(cid)
    for r in rows:
        m = r.get("meta")
        if isinstance(m, dict):
            continue                      # memory уже отдаёт словарь, парсить нечего
        try:
            r["meta"] = json.loads(m or "{}")
        except Exception:
            r["meta"] = {}
    return {"messages": rows}



@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        return JSONResponse({"error": "файл больше 64мб"}, status_code=413)
    if not data:
        return JSONResponse({"error": "пустой файл"}, status_code=400)
    p = vision.save_upload(data, file.filename or "file", UPLOAD_DIR)
    is_img = _is_image(data, file.content_type or "", p.name)
    log.info("загрузка %s (%.1f кб) тип=%s", p.name, len(data) / 1024, "image" if is_img else "file")
    return {"name": p.name, "path": str(p), "kind": "image" if is_img else "file",
            "bytes": len(data), "url": "/files/" + p.name}


@app.get("/attach/{name}")
async def get_attach(name: str, user: str = Depends(current_user)):
    safe = Path(name).name
    p = ATTACH_DIR / safe
    if not p.is_file():
        p = UPLOAD_DIR / safe
    if not p.is_file():
        raise HTTPException(404, "нет файла")
    media = None
    if re.search(r"\.(png|jpe?g|gif|webp|avif|bmp|svg)$", safe, re.I):
        import mimetypes
        media = mimetypes.guess_type(safe)[0]
    return FileResponse(p, filename=safe, media_type=media)


@app.get("/files/{name}")
async def get_file(name: str, user: str = Depends(current_user)):
    safe = Path(name).name
    p = UPLOAD_DIR / safe
    if not p.is_file():
        raise HTTPException(404, "нет файла")
    return FileResponse(p, filename=safe)



TURN_KEEP = 600          # сколько секунд после конца хода его журнал доступен для подписки


def sse(obj):
    d = json.dumps(obj, ensure_ascii=False)
    i = obj.get("seq")
    head = ("id: %d\n" % i) if i else ""
    return head + "data: " + d + "\n\n"


class Turn:
    """живой ход агента: журнал событий + подписчики.
    живёт на сервере независимо от браузера: f5, обрыв связи и закрытие
    вкладки ход не убивают, ответ в любом случае ложитcя в базу"""

    def __init__(self, cid: int):
        self.cid = cid
        self.seq = 0
        self.events = []          # весь журнал хода, для снимка новым подписчикам
        self.subs = set()         # очереди подписчиков-стримов
        self.task = None
        self.answer = ""          # текст, накопленный по ходу (для частичного сохранения)
        self.thought = ""         # ход мыслей
        self.steps = []           # tool/tool_done для meta в базе
        self.attached = []        # вложения, отданные этим ходом
        self.sites = []           # сайты, опубликованные этим ходом
        self.status = ""          # последняя подпись состояния («думает», «продолжаю»)
        self.stopped = False
        self.saved = False
        self.done = False
        self.finished_at = 0.0

    def state(self):
        """снимок хода одним куском. страховка от обрыва sse: фронт опрашивает это
        и доедает хвост, даже если стрим умер совсем"""
        return {"active": not self.done, "done": self.done, "seq": self.seq,
                "answer": self.answer, "thought": self.thought[-8000:],
                "steps": self.steps, "attached": self.attached, "sites": self.sites,
                "status": self.status, "stopped": self.stopped}

    def emit(self, e):
        self.seq += 1
        e = dict(e)
        e["seq"] = self.seq
        self.events.append(e)
        t = e.get("t")
        if t == "text":
            self.answer += e.get("d") or ""
        elif t == "reason":
            self.thought += str(e.get("d") or "")
        elif t in ("tool", "tool_done"):
            self.steps.append(e)
        elif t == "attach":
            self.attached.append({k: e.get(k) for k in ("name", "url", "kind", "caption")})
        elif t == "site":
            self.sites.append({"slug": e.get("slug"), "url": e.get("url")})
        elif t == "status":
            self.status = str(e.get("d") or "")
        elif t == "stopped":
            self.stopped = True
        elif t == "done":
            a = e.get("answer")
            if a:
                self.answer = a
        for q in list(self.subs):
            try:
                q.put_nowait(e)
            except Exception:
                pass


_turns: dict = {}


def _gc_turns():
    now = time.time()
    for k in [k for k, t in _turns.items()
              if t.done and now - t.finished_at > TURN_KEEP]:
        _turns.pop(k, None)


@app.post("/api/chats/{cid}/send")
async def send(cid: int, request: Request, user: dict = Depends(current_user)):
    body = await _json(request)
    text = (body.get("text") or "").strip()
    files = body.get("files") or []
    req_mode = str(body.get("mode") or "").strip().lower()
    if not text and not files:
        return JSONResponse({"error": "пусто"}, status_code=400)

    if cid and cid > 0:
        _own_chat(cid, user)
        chat_mode = memory.chat_mode(cid)
    else:
        chat_mode = memory.user_mode(user["id"])
        cid = memory.create_chat(text[:60] if text else "", uid=user["id"], mode=chat_mode)
        log.info("создан чат %s юзером %s, режим %s", cid, user["login"], chat_mode)
    if req_mode:
        chat_mode = req_mode
        memory.set_chat_mode(cid, req_mode)

    _gc_turns()
    old = _turns.get(cid)
    if old and not old.done:
        return JSONResponse({"error": "предыдущий ответ ещё пишется, секунду"}, status_code=409)

    meta_files = []
    files = [f for f in files if isinstance(f, dict)][:8]
    for f in files:
        p = Path(str(f.get("path", "")))
        if p.is_file() and p.parent == UPLOAD_DIR:
            meta_files.append({"name": p.name, "kind": f.get("kind") or "file",
                               "url": "/files/" + p.name})

    user_id = memory.add_message(cid, "user", text, {"files": meta_files})
    hist = memory.history(cid, HISTORY_LIMIT)

    turn = Turn(cid)
    _turns[cid] = turn

    def save_partial():
        """ход прервали до конца: сохраняем что успело, чтобы ответ не пропал"""
        if turn.saved or not turn.answer.strip():
            return
        try:
            memory.add_message(cid, "assistant", turn.answer,
                               {"steps": turn.steps, "files": meta_files, "partial": True})
            turn.saved = True
            log.info("сохранил недописанный ответ чата %s (%s симв)", cid, len(turn.answer))
        except Exception as e:
            log.warning("недописанный ответ не сохранился: %s", e)

    async def work():
        """ход агента. крутится на сервере независимо от подключений:
        даже если все браузеры ушли, ответ ляжет в базу"""
        try:
            images = []
            for f in files:
                p2 = Path(str(f.get("path", "")))
                if p2.is_file() and p2.parent == UPLOAD_DIR and f.get("kind") == "image":
                    try:
                        images.append({"data": p2.read_bytes(), "mime": "image/jpeg",
                                       "caption": text, "name": p2.name})
                    except Exception as e:
                        log.warning("фото не прочиталось: %s", e)
            result = await stream_turn(hist, turn.emit, images,
                                       user={"id": user["id"], "login": user["login"],
                                             "pname": user.get("pname"), "is_owner": user.get("is_owner")},
                                       mode=chat_mode, model=memory.user_model(user["id"]))
            if isinstance(result, tuple):
                answer = result[0] if len(result) > 0 else ""
                used = result[1] if len(result) > 1 else 0
                rmeta = result[2] if len(result) > 2 else {}
            else:
                answer, used, rmeta = str(result or ""), 0, {}
            meta = {"steps": turn.steps, "files": meta_files}
            if isinstance(rmeta, dict):
                meta.update({k: v for k, v in rmeta.items() if v})
            memory.add_message(cid, "assistant", answer, meta, tokens=used)
            turn.saved = True
            ch = [c for c in memory.list_chats(200, uid=user["id"]) if c["id"] == cid]
            if ch and not ch[0]["title"] and text:
                memory.rename_chat(cid, text[:60])
            memory.drop_empty_chats()
        except asyncio.CancelledError:
            save_partial()
            turn.emit({"t": "stopped"})
        except Exception as e:
            log.exception("ход упал")
            save_partial()
            turn.emit({"t": "error", "d": "%s: %s" % (type(e).__name__, e)})
        finally:
            turn.done = True
            turn.finished_at = time.time()
            turn.emit({"t": "end"})

    turn.emit({"t": "start", "chat": cid, "mode": chat_mode, "user_msg": user_id})
    turn.task = asyncio.create_task(work())
    log.info("ход запущен: чат=%s юзер=%s режим=%s", cid, user["login"], chat_mode)
    return {"chat": cid, "user_msg": user_id, "mode": chat_mode}


@app.get("/api/chats/{cid}/stream")
async def turn_stream(cid: int, request: Request, user: dict = Depends(current_user)):
    """подписка на ход: снимок журнала (или хвост после Last-Event-ID) + живые события.
    браузер может отваливаться сколько угодно: EventSource сам переедет и продолжит с места обрыва"""
    if not 0 < cid < MAX_CID:
        raise HTTPException(404, "нет чата")
    _own_chat(cid, user)
    try:
        since = int(request.headers.get("last-event-id")
                    or request.query_params.get("since") or 0)
    except Exception:
        since = 0

    async def gen():
        t = _turns.get(cid)
        if not t or (t.done and time.time() - t.finished_at > TURN_KEEP):
            yield sse({"t": "idle"})
            return
        q: asyncio.Queue = asyncio.Queue()
        t.subs.add(q)
        last = since
        try:
            # снимок: всё, что клиент ещё не видел
            for e in list(t.events):
                if e.get("seq", 0) > last:
                    last = e["seq"]
                    yield sse(e)
            if t.done:
                yield sse({"t": "end"})
                return
            # маркер: дальше идут только живые события. фронт по нему понимает,
            # что ход ещё пишется, а не проигрывает старый снимок
            yield sse({"t": "live"})
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=5)
                except asyncio.TimeoutError:
                    # пинг чаще: cloudflare рвёт соединение, если по нему долго нет байтов
                    yield ": ping\n\n"
                    continue
                if e is None:
                    break
                if e.get("seq", 0) > last:
                    last = e["seq"]
                    yield sse(e)
                if e.get("t") == "end":
                    break
        finally:
            t.subs.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.get("/api/chats/{cid}/turn")
async def turn_state(cid: int, user: dict = Depends(current_user)):
    """состояние хода одним json: текст, мысли, шаги, вложения.
    фронт опрашивает это, пока идёт ход, поэтому обрыв sse больше ничего не теряет"""
    if not 0 < cid < MAX_CID:
        raise HTTPException(404, "нет чата")
    _own_chat(cid, user)
    t = _turns.get(cid)
    if not t:
        return {"active": False, "done": True, "seq": 0, "answer": "", "thought": "",
                "steps": [], "attached": [], "sites": [], "status": "", "stopped": False}
    return t.state()


@app.post("/api/chats/{cid}/stop")
async def stop_turn(cid: int, user: dict = Depends(current_user)):
    """настоящий стоп: отменяем ход на сервере, недописанное уходит в базу"""
    _own_chat(cid, user)
    t = _turns.get(cid)
    if t and not t.done and t.task and not t.task.done():
        t.task.cancel()
        return {"ok": True}
    return {"ok": False}


@app.get("/api/turns")
async def active_turns(user: dict = Depends(current_user)):
    """какие чаты юзера сейчас пишут ответ: фронт подхватывает их после f5"""
    _gc_turns()
    mine = []
    for k, t in _turns.items():
        # только реально пишущиеся ходы. завершённые (даже свежие, ещё не gc-нутые)
        # сюда попадать не должны: их ответ уже в базе, а живой блок поверх истории
        # выглядел бы как фантомный «думаю» с проигрышем старого ответа
        if t.done:
            continue
        try:
            if memory.chat_owner(k) == user["id"]:
                mine.append(t)
        except Exception:
            pass
    mine.sort(key=lambda t: -t.finished_at)
    return {"cids": [t.cid for t in mine]}



@app.get("/api/admin/users")
async def admin_users(user: dict = Depends(admin_user)):
    users = memory.list_users()
    for u in users:
        u.pop("phash", None)          # хеш пароля наружу не отдаём никогда
    return {"users": users}


@app.post("/api/admin/users")
async def admin_add_user(request: Request, user: dict = Depends(admin_user)):
    body = await _json(request)
    login = (body.get("login") or "").strip()
    pw = (body.get("password") or "").strip()
    if len(login) < 3:
        return JSONResponse({"error": "логин минимум 3 символа"}, status_code=400)
    if len(pw) < 6:
        return JSONResponse({"error": "пароль минимум 6 символов"}, status_code=400)
    try:
        r = memory.add_user(login, pw, body.get("pname") or login,
                            is_owner=0,
                            limit_day=int(body.get("limit_day") or 100),
                            web=1 if body.get("web", True) else 0)
    except Exception as e:
        log.exception("не вышло создать юзера %s", login)
        return JSONResponse({"error": "сбой: %s" % e}, status_code=500)
    if r.get("error"):
        return JSONResponse(r, status_code=400)
    log.info("создан пользователь %s", login)
    return r


@app.post("/api/admin/switch/{uid}")
async def admin_switch(uid: int, request: Request, user: dict = Depends(admin_user)):
    """владелец заходит под другим аккаунтом без пароля. обратный путь остаётся в подписанной куке"""
    t = memory.user_by_id(uid)
    if not t:
        raise HTTPException(404, "нет такого аккаунта")
    if t.get("disabled"):
        raise HTTPException(400, "аккаунт отключён")
    # под кем вернёмся: если уже переключены — исходный владелец, иначе текущий владелец
    back = user["id"]
    if user.get("impersonated"):
        for u in memory.list_users():
            if u.get("is_owner") and u["login"] == user.get("back_login"):
                back = u["id"]
                break
    log.info("владелец %s переключился на %s", user["login"], t["login"])
    resp = JSONResponse({"ok": True, "login": t["login"], "name": t.get("pname") or t["login"]})
    resp.set_cookie(COOKIE_NAME, make_cookie(t["id"], back), max_age=COOKIE_DAYS * 86400,
                    httponly=True, samesite="lax", secure=True, path="/")
    return resp


@app.post("/api/admin/back")
async def admin_back(user: dict = Depends(current_user)):
    """вернуться к своему аккаунту"""
    if not user.get("impersonated"):
        return {"ok": True, "was": False}
    o = None
    for u in memory.list_users():
        if u.get("is_owner") and u["login"] == user.get("back_login"):
            o = u
            break
    if not o:
        raise HTTPException(404, "владелец не найден")
    resp = JSONResponse({"ok": True, "login": o["login"], "name": o.get("pname") or o["login"]})
    resp.set_cookie(COOKIE_NAME, make_cookie(o["id"], 0), max_age=COOKIE_DAYS * 86400,
                    httponly=True, samesite="lax", secure=True, path="/")
    return resp


@app.post("/api/admin/users/{uid}/password")
async def admin_set_pw(uid: int, request: Request, user: dict = Depends(admin_user)):
    body = await _json(request)
    pw = (body.get("password") or "").strip()
    if len(pw) < 6:
        return JSONResponse({"error": "пароль минимум 6 символов"}, status_code=400)
    tgt = memory.user_by_id(uid)
    if not tgt:
        return JSONResponse({"error": "нет такого"}, status_code=404)
    memory.set_password(uid, pw)
    log.info("пароль изменён для %s владельцем", tgt["login"])
    return {"ok": True}


@app.patch("/api/admin/users/{uid}")
async def admin_patch_user(uid: int, request: Request, user: dict = Depends(admin_user)):
    body = await _json(request)
    tgt = memory.user_by_id(uid)
    if not tgt:
        return JSONResponse({"error": "нет такого"}, status_code=404)
    fields = {}
    if "pname" in body:
        fields["pname"] = str(body["pname"])[:40]
    if "limit_day" in body:
        fields["limit_day"] = int(body["limit_day"] or 0)
    if "web" in body:
        fields["web"] = 1 if body["web"] else 0
    if "disabled" in body:
        fields["disabled"] = 1 if body["disabled"] else 0
    if fields.get("disabled") and tgt.get("is_owner"):
        return JSONResponse({"error": "себя выключить нельзя"}, status_code=400)
    memory.set_user(uid, **fields)
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
async def admin_del_user(uid: int, user: dict = Depends(admin_user)):
    r = memory.delete_user(uid)
    if r.get("error"):
        return JSONResponse(r, status_code=400)
    log.info("удалён пользователь id=%s владельцем", uid)
    return r


@app.get("/api/admin/overview")
async def admin_overview(user: dict = Depends(admin_user)):
    """здоровье сервера одним запросом"""
    import shutil
    import subprocess

    def sh(cmd):
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=6).stdout.strip()
        except Exception:
            return ""

    st = memory.stats()
    du = shutil.disk_usage("/")
    vm = {}
    for line in sh("free -m").splitlines():
        if line.startswith("Mem:"):
            p2 = line.split()
            vm = {"total": int(p2[1]), "used": int(p2[2]), "free": int(p2[3]), "avail": int(p2[6])}
    services = {}
    for name in ("nginx", "ai-agent", "drop"):
        services[name] = sh(f"systemctl is-active {name}") or "неизвестно"
    load = sh("cat /proc/loadavg").split()[:3]
    used_pct = round(du.used / du.total * 100)
    return {
        "stats": st,
        "disk": {"total_gb": round(du.total / 1e9, 1), "used_gb": round(du.used / 1e9, 1),
                 "free_gb": round(du.free / 1e9, 1), "percent": used_pct},
        "mem_mb": vm,
        "services": services,
        "load": load,
        "uptime": sh("uptime -p"),
        "docker": sh("docker ps --format '{{.Names}}' | tr '\n' ' '"),
    }


@app.get("/api/status")
async def status_light(user: dict = Depends(current_user)):
    """лёгкая сводка: доступна всем, ничего секретного"""
    import shutil
    import subprocess

    def sh(cmd):
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=6).stdout.strip()
        except Exception:
            return ""

    du = shutil.disk_usage("/")
    vm = {}
    for line in sh("free -m").splitlines():
        if line.startswith("Mem:"):
            p2 = line.split()
            if len(p2) > 6:
                vm = {"total": int(p2[1]), "used": int(p2[2]), "avail": int(p2[6])}
            else:
                vm = {"total": int(p2[1]), "used": int(p2[2]), "avail": int(p2[3])}
    used_pct = round(du.used / du.total * 100)
    return {"disk_free_gb": round(du.free / 1e9, 1), "disk_percent": used_pct,
            "mem": vm, "load": sh("cat /proc/loadavg").split()[:3],
            "uptime": sh("uptime -p")}


@app.get("/api/myusage")
async def my_usage(user: dict = Depends(current_user)):
    uid = user["id"]
    return {"today": memory.today_usage(uid),
            "limit": user.get("limit_day") or 0,
            "owner": bool(user.get("is_owner")),
            "days": memory.usage_days(uid, 30),
            "totals": memory.usage_totals(uid),
            "mode": memory.user_mode(uid),
            "model": memory.user_model(uid)}



@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


def _ver():
    try:
        return str(int(max(f.stat().st_mtime for f in STATIC_DIR.glob("*"))))
    except Exception:
        return "1"


_ADMIN_START = "<!--ADMIN-->"
_ADMIN_END = "<!--/ADMIN-->"


def _page(name: str, owner: bool = False):
    html = (STATIC_DIR / name).read_text()
    # админку вырезаем на сервере: кенты её вообще не получают, кэш тут не помеха
    if not owner:
        while _ADMIN_START in html and _ADMIN_END in html:
            a = html.index(_ADMIN_START)
            b = html.index(_ADMIN_END, a) + len(_ADMIN_END)
            html = html[:a] + html[b:]
    v = _ver()
    html = html.replace("/static/style.css", "/static/style.css?v=" + v)
    html = html.replace("/static/app.js", "/static/app.js?v=" + v)
    html = html.replace("/static/theme.js", "/static/theme.js?v=" + v)
    html = html.replace("/static/lucide.min.js", "/static/lucide.min.js?v=" + v)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/")
async def index(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    uid = check_cookie(token) if token else 0
    u = memory.user_by_id(uid) if uid else None
    if not u:
        return _page("login.html")
    return _page("index.html", owner=bool(u.get("is_owner")))


@app.get("/static/{name}")
async def static_files(name: str):
    p = STATIC_DIR / Path(name).name
    if not p.is_file():
        raise HTTPException(404, "нет файла")
    media = {"css": "text/css", "js": "application/javascript", "svg": "image/svg+xml",
             "png": "image/png", "webmanifest": "application/manifest+json",
             "html": "text/html; charset=utf-8"}.get(
        p.suffix.lstrip("."), "text/plain")
    return FileResponse(p, media_type=media,
                        headers={"Cache-Control": "no-cache, must-revalidate"})
