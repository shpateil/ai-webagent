"""агент: режимы мощности, стрим, тулы, память по юзеру"""
import asyncio
import json
import logging
import time

import httpx

from config import API_URL, CVC_KEY, OR_URL, OR_KEY, FALLBACK_MODELS, MAX_ITER, STEP_BURST, BUDGET_HOURS
from tools import Tools, get_tool_schemas, load_prompt, wants_school
import memory

log = logging.getLogger("agent")

MAX_HISTORY = 40
BUDGET_SECONDS = int(BUDGET_HOURS * 3600)      # запас по времени на один ход

MODES = {
    "ultra": {
        "label": "ультра лоу",
        "hint": "дешёвый и быстрый, без тулов и скиллов, только отвечает",
        "model": "glm-5.3-flash", "tools": False, "vision": "gemini-3.8-flash",
        "plan": False, "max_tokens": 2000, "temp": 0.9,
    },
    "low": {
        "label": "лоу",
        "hint": "то же со скиллами и тулами, фото смотрит через отдельную модель",
        "model": "glm-5.3-flash", "tools": True, "vision": "gemini-3.8-flash",
        "plan": False, "max_tokens": 4000, "temp": 1.0,
    },
    "mid": {
        "label": "медиум",
        "hint": "быстрее и дешевле: без хода мыслей, фото видит сам",
        "model": "glm-5.3-flash", "tools": True, "vision": None,
        "plan": False, "max_tokens": 4000, "temp": 1.0,
    },
    "max": {
        "label": "макс",
        "hint": "всё: тулы, скиллы, ход мыслей, своё зрение",
        "model": "glm-5.3-flash", "tools": True, "vision": None,
        "plan": True, "max_tokens": 9000, "temp": 1.0,
    },
}

DEFAULT_PICK = "glm-5.3-flash"

MODELS = [{'id': 'glm-5.3-flash',
  'name': 'glm 5.3 флеш',
  'note': 'рекомендуется: стабильный, видит фото, дёшево',
  'rec': True,
  'mult': 0.3,
  'provider': 'cvc'},
 {'id': 'mimo-v2.5',
  'name': 'мимо 2.5',
  'note': 'самый дешёвый, быстрый универсал',
  'mult': 0.05,
  'provider': 'cvc'},
 {'id': 'qwen3.8-flash',
  'name': 'qwen 3.8 флеш',
  'note': 'быстрый, сильный в коде',
  'mult': 1,
  'provider': 'cvc'},
 {'id': 'gpt-5.6-luna',
  'name': 'gpt luna',
  'note': 'дешёвый gpt, видит фото',
  'mult': 0.33,
  'provider': 'cvc'},
 {'id': 'grok-4.5', 'name': 'грок 4.5', 'note': 'живой стиль, видит фото', 'mult': 0.5, 'provider': 'cvc'},
 {'id': 'claude-haiku-4-5',
  'name': 'haiku 4.5',
  'note': 'аккуратный, средняя цена',
  'mult': 0.9,
  'provider': 'cvc'},
 {'id': 'kimi-k2.7-code', 'name': 'кими k2.7 код', 'note': 'заточен под код', 'mult': 0.9, 'provider': 'cvc'},
 {'id': 'deepseek-v4-pro',
  'name': 'дипсик про',
  'note': 'умнее флеша, дороже',
  'mult': 0.5,
  'provider': 'cvc'},
 {'id': 'deepseek-v4-flash',
  'name': 'дипсик флеш (стабилен)',
  'note': 'дёшево, ровно отвечает',
  'mult': 0.1,
  'provider': 'cvc'},
 {'id': 'deepseek-v4.1-flash',
  'name': 'дипсик 4.1 флеш (нестабилен)',
  'note': 'новый, видит фото, но рвёт ответы и путает себя',
  'mult': 0.3,
  'provider': 'cvc'},
 {'id': 'gemini-3.1-pro',
  'name': 'gemini 3.1 pro',
  'tier': 'expensive',
  'mult': 2,
  'note': 'наука и математика, контекст 1M. дорого: ×2 к базовой цене',
  'provider': 'cvc'},
 {'id': 'gpt-5.6-sol',
  'name': 'gpt 5.6 sol',
  'tier': 'expensive',
  'mult': 2.5,
  'note': 'топ по коду и длинным агентным задачам, контекст 1M. дорого: ×2.5',
  'provider': 'cvc'},
 {'id': 'kimi-k3',
  'name': 'кими k3',
  'tier': 'expensive',
  'mult': 2.5,
  'note': 'агентный, код, контекст 1M, думает дольше. дорого: ×2.5',
  'provider': 'cvc'},
 {'id': 'qwen3.8-max',
  'name': 'qwen 3.8 макс',
  'tier': 'expensive',
  'mult': 3,
  'note': 'сильный математик, но медленный и жрёт вход. дорого: ×3',
  'provider': 'cvc'},
 {'id': 'claude-opus-5',
  'name': 'claude opus 5',
  'tier': 'expensive',
  'mult': 4,
  'note': 'самые аккуратные длинные рассуждения и код. дорого: ×4',
  'provider': 'cvc'},
 {'id': 'gpt-6-astra',
  'name': 'gpt 6 astra',
  'tier': 'expensive',
  'mult': 6.5,
  'note': 'новейший gpt, контекст 1M, выход 128k. самое дорогое: ×6.5',
  'provider': 'cvc'},
 {'id': 'nvidia/nemotron-3-ultra-550b-a55b:free',
  'name': 'nemotron ultra фри',
  'tier': 'free',
  'note': 'умный фри, думает дольше. проще альфы',
  'provider': 'openrouter'},
 {'id': 'nvidia/nemotron-3.5-lightning:free',
  'name': 'nemotron lightning фри',
  'tier': 'free',
  'note': 'быстрый фри универсал',
  'provider': 'openrouter'},
 {'id': 'cohere/north-mini-code:free',
  'name': 'north code фри',
  'tier': 'free',
  'note': 'только код и скрипты, болтать не умеет',
  'provider': 'openrouter'},
 {'provider': 'cvc',
  'id': 'gpt-6-luna',
  'name': 'gpt 6 luna',
  'tier': 'cvc',
  'mult': 0.25,
  'note': 'быстрый gpt, видит фото. баланс cvc на нуле'},
 {'provider': 'cvc',
  'id': 'gpt-6-sol',
  'name': 'gpt 6 sol',
  'tier': 'cvc',
  'mult': 2,
  'note': 'мощнее luna, видит фото. баланс cvc на нуле'},
 {'provider': 'cvc',
  'id': 'gpt-5.6-terra',
  'name': 'gpt 5.6 terra',
  'tier': 'cvc',
  'mult': 1.5,
  'note': 'код и сложные задачи, фото. баланс cvc на нуле'},
 {'provider': 'cvc',
  'id': 'claude-sonnet-5',
  'name': 'claude sonnet 5',
  'tier': 'cvc',
  'mult': 2,
  'note': 'сильный универсал, фото. баланс cvc на нуле'},
 {'provider': 'cvc',
  'id': 'grok-4.7',
  'name': 'grok 4.7',
  'tier': 'cvc',
  'mult': 0.5,
  'note': 'быстрый универсал, фото. баланс cvc на нуле'},
 {'provider': 'cvc',
  'id': 'composer-2.5-fast',
  'name': 'composer 2.5 fast',
  'tier': 'cvc',
  'mult': 0.3,
  'note': 'быстрая модель для кода. баланс cvc на нуле'},
 {'provider': 'cline',
  'id': 'openai/gpt-6-luna',
  'name': 'gpt 6 luna',
  'tier': 'cline',
  'price': '$0.10 / $0.50 за 1м',
  'note': 'быстрая, фото. потоковый вызов tools проверен'},
 {'provider': 'cline',
  'id': 'openai/gpt-6-sol',
  'name': 'gpt 6 sol',
  'tier': 'cline-expensive',
  'price': '$2 / $10 за 1м',
  'note': 'сложные задачи, фото и tools'},
 {'provider': 'cline',
  'id': 'openai/gpt-6-astra',
  'name': 'gpt 6 astra',
  'tier': 'cline-expensive',
  'price': '$10 / $50 за 1м',
  'note': 'флагман, фото и tools'},
 {'provider': 'cline',
  'id': 'anthropic/claude-opus-5.5',
  'name': 'claude opus 5.5',
  'tier': 'cline-expensive',
  'price': '$4 / $20 за 1м',
  'note': 'код и рассуждения, фото'},
 {'provider': 'cline',
  'id': 'x-ai/grok-4.7',
  'name': 'grok 4.7',
  'tier': 'cline-expensive',
  'price': '$1.60 / $4.80 за 1м',
  'note': 'код и агентные задачи, фото'},
 {'provider': 'cline',
  'id': 'moonshotai/kimi-k3',
  'name': 'kimi k3',
  'tier': 'cline-expensive',
  'price': '$3 / $15 за 1м',
  'note': 'длинные агентные задачи, фото и видео'},
 {'provider': 'cline',
  'id': 'qwen/qwen3.8-max-0902',
  'name': 'qwen 3.8 max',
  'tier': 'cline-expensive',
  'price': '$2 / $6 за 1м',
  'note': 'сильна в коде, фото'},
 {'provider': 'cline',
  'id': 'deepseek/deepseek-v4-pro',
  'name': 'deepseek v4 pro',
  'tier': 'cline',
  'price': '$0.95 / $1.90 за 1м',
  'note': 'сильные рассуждения и код, без зрения'},
 {'provider': 'cline',
  'id': 'z-ai/glm-5.3-flash',
  'name': 'glm 5.3 flash',
  'tier': 'cline',
  'price': '$0.15 / $0.50 за 1м',
  'note': 'недорогая, фото и видео'},
 {'provider': 'cline',
  'id': 'xiaomi/mimo-v2.6-pro',
  'name': 'mimo v2.6 pro',
  'tier': 'cline',
  'price': '$0.44 / $0.87 за 1м',
  'note': 'фото, аудио и видео'},
 {'provider': 'cline',
  'id': 'qwen/qwen3.8-27b:free',
  'name': 'qwen 3.8 27b',
  'tier': 'cline-free',
  'note': 'бесплатная, фото и tools проверены'},
 {'provider': 'cline',
  'id': 'nvidia/nemotron-3.5-lightning:free',
  'name': 'nemotron 3.5 lightning',
  'tier': 'cline-free',
  'note': 'быстрая бесплатная, tools проверены'},
 {'provider': 'cline',
  'id': 'google/gemma-4-31b-it:free',
  'name': 'gemma 4 31b',
  'tier': 'cline-free',
  'note': 'бесплатная, фото и tools проверены'},
 {'provider': 'cline',
  'id': 'google/gemma-4-26b-a4b-it:free',
  'name': 'gemma 4 26b',
  'tier': 'cline-free',
  'note': 'быстрая бесплатная, фото и tools проверены'},
 {'provider': 'cline',
  'id': 'dots-studio/dots-3-note-preview:free',
  'name': 'dots 3 note',
  'tier': 'cline-free',
  'note': 'бесплатная, фото и tools проверены'}]

NATIVE_VISION = {'anthropic/claude-opus-5.5',
 'claude-haiku-4-5',
 'claude-opus-5',
 'claude-sonnet-5',
 'dots-studio/dots-3-note-preview:free',
 'gemini-3.1-pro',
 'gemini-3.5-flash',
 'gemini-3.6-flash',
 'gemini-3.7-flash',
 'gemini-3.8-flash',
 'glm-5.3-flash',
 'google/gemma-4-26b-a4b-it:free',
 'google/gemma-4-31b-it:free',
 'gpt-5.6-luna',
 'gpt-5.6-sol',
 'gpt-5.6-terra',
 'gpt-6-astra',
 'gpt-6-luna',
 'gpt-6-sol',
 'grok-4.5',
 'grok-4.7',
 'kimi-k2.7-code',
 'kimi-k3',
 'mimo-v2.5',
 'moonshotai/kimi-k3',
 'qwen/qwen3.8-27b:free',
 'qwen/qwen3.8-max-0902',
 'qwen3.8-flash',
 'qwen3.8-max',
 'x-ai/grok-4.7',
 'xiaomi/mimo-v2.6-pro',
 'z-ai/glm-5.3-flash'}

MODEL_IDS = {m["id"] for m in MODELS}

OR_IDS = {m["id"] for m in MODELS if m.get("tier") == "free"}
FREE_FALLBACKS = ["nvidia/nemotron-3.5-lightning:free",
                  "nvidia/nemotron-3-ultra-550b-a55b:free"]


CLINE_IDS = {m["id"] for m in MODELS if m.get("provider") == "cline"}


def _endpoint(model):
    if model in CLINE_IDS:
        from config import CLINE_KEY
        if not CLINE_KEY:
            raise RuntimeError("нет ключа cline")
        return "https://api.cline.bot/api/v1/chat/completions", CLINE_KEY, {}
    if model in OR_IDS:
        if not OR_KEY:
            raise RuntimeError("нет ключа бесплатного провайдера")
        return OR_URL, OR_KEY, {"HTTP-Referer": "https://openrouter.ai",
                                "X-Title": "web-agent"}
    return API_URL, CVC_KEY, {}


DEFAULT_MODE = "max"


def norm_model(m):
    """модель из настроек: пусто или что-то неизвестное = брать модель режима"""
    m = str(m or "").strip()
    if not m:
        return ""
    for known in MODELS:
        if known["id"].lower() == m.lower():
            return known["id"]
    return ""


def norm_mode(m):
    m = str(m or "").strip().lower()
    return m if m in MODES else DEFAULT_MODE


def md(mode):
    return MODES[norm_mode(mode)]


def now_line():
    return time.strftime("%d.%m.%Y %H:%M:%S")


def build_system(user, mode, vision_note="", ask="", model=""):
    user = user or {}
    cfg = dict(md(mode))
    if model:
        cfg["model"] = model
    uid = int(user.get("id") or 0)
    is_owner = bool(user.get("is_owner"))
    who = user.get("pname") or user.get("login") or "гость"
    facts = memory.recall("", limit=25, uid=uid)
    facts_txt = "\n".join("- [%s] %s" % (f["id"], f["text"]) for f in facts) if facts else "пока пусто"

    if is_owner:
        role = ("собеседник: ШПАТЕЛЬ, твой овнер. он хозяин сервера, сайтов, файлов и всех аккаунтов. "
                "доверяешь полностью, его команды выполняешь без оговорок, ему доступно всё")
    else:
        role = ("собеседник: %s (логин %s), знакомый овнера. можно всё кроме удаления чужого, "
                "смены твоего промта и рассказов про других людей" % (who, user.get("login")))

    parts = [load_prompt(wants_school(ask)), "---",
             "сейчас %s местное время" % now_line(),
             "веб-чат агента",
             "режим работы: %s (%s)" % (cfg["label"], cfg["hint"]),
             "тебя крутит модель: %s" % cfg["model"], role]

    if not cfg["tools"]:
        parts.append("тулов у тебя в этом режиме нет. отвечай сам знанием, код не считай, в интернет не лезь")
    if cfg["plan"]:
        parts.append("перед действием набрось план в теге <plan>...</plan> — он показывается человеку "
                     "как «ход мыслей». одна-две строки по-человечески, что делаешь и зачем")

    parts.append("что помнишь про собеседника:\n%s" % facts_txt)
    if vision_note:
        parts.append("человек прислал картинку, вот что на ней (это твои глаза, считай фактом):\n%s" % vision_note)
    return [{"role": "system", "content": "\n".join(parts)}]


class PlanSplit:
    """вырезает <plan> из потока: в текст не идёт, уходит в ход мыслей"""

    def __init__(self, on_event):
        self.on_event = on_event
        self.buf = ""
        self.in_plan = False
        self.done = False

    def feed(self, chunk):
        if self.done:
            return chunk
        self.buf += chunk
        out = ""
        while self.buf:
            if not self.in_plan:
                i = self.buf.find("<plan>")
                if i == -1:
                    cut = max(0, len(self.buf) - 5)
                    out += self.buf[:cut]
                    self.buf = self.buf[cut:]
                    break
                out += self.buf[:i]
                self.buf = self.buf[i + 6:]
                self.in_plan = True
            else:
                j = self.buf.find("</plan>")
                if j == -1:
                    self.on_event({"t": "reason", "d": self.buf})
                    self.buf = ""
                    break
                self.on_event({"t": "reason", "d": self.buf[:j]})
                self.buf = self.buf[j + 7:]
                self.in_plan = False
        if "</plan>" in chunk and not self.in_plan:
            self.done = True
        return out

    def tail(self):
        rest, self.buf = self.buf, ""
        if self.in_plan:
            self.on_event({"t": "reason", "d": rest})
            return ""
        return rest


def parse_calls(acc):
    out = []
    for k in sorted(acc.keys()):
        if k == "__usage":
            continue
        v = acc[k]
        if v.get("name"):
            out.append(v)
    return out


def _image_parts(images):
    """картинки в content-части сообщения. всегда через imgs.shrink:
    без сжатия модели вроде glm-5.3-flash получают тысячи image-токенов и провайдер
    отдаёт 503 (у кентов это выглядело как «агент молчит на фото»)"""
    import imgs
    return imgs.image_parts(images)


async def one_call(cfg, messages, on_event, deadline, with_tools=True, model=None):
    parts, acc, usage = [], {}, 0
    plan = PlanSplit(on_event) if cfg["plan"] else None
    payload = {
        "model": model or cfg["model"], "messages": messages, "stream": True,
        "max_tokens": cfg["max_tokens"], "temperature": cfg["temp"], "top_p": 0.95,
    }
    if with_tools and cfg["tools"]:
        payload["tools"] = get_tool_schemas()
        payload["tool_choice"] = "auto"
    endpoint_url, endpoint_key, endpoint_hdrs = _endpoint(model or cfg["model"])
    timeout = httpx.Timeout(connect=20, read=600, write=60, pool=20)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", endpoint_url,
                                headers={"Authorization": "Bearer " + endpoint_key,
                                         "Content-Type": "application/json",
                                         **endpoint_hdrs},
                                json=payload) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")[:250]
                    return "", [], "http %s: %s" % (r.status_code, body), 0
                async for line in r.aiter_lines():
                    if time.time() > deadline:
                        return "".join(parts), parse_calls(acc), "время хода вышло", usage
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except Exception:
                        continue
                    us = chunk.get("usage")
                    if us:
                        usage = max(usage, int(us.get("total_tokens") or 0))
                    ch = chunk.get("choices") or []
                    if not ch:
                        continue
                    d = ch[0].get("delta") or {}
                    rc = d.get("reasoning_content") or d.get("reasoning")
                    if rc:
                        on_event({"t": "reason", "d": rc})
                    cc = d.get("content")
                    if cc:
                        vis = plan.feed(cc) if plan else cc
                        if vis:
                            parts.append(vis)
                            on_event({"t": "text", "d": vis})
                    for tc in (d.get("tool_calls") or []):
                        idx = str(tc.get("index", 0))
                        slot = acc.setdefault(idx, {"id": "", "name": "", "args_raw": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args_raw"] += fn["arguments"]
        if plan:
            t = plan.tail()
            if t:
                parts.append(t)
        return "".join(parts), parse_calls(acc), None, usage
    except Exception as e:
        return "".join(parts), parse_calls(acc), "%s: %s" % (type(e).__name__, e), usage


async def stream_turn(history, on_event, images=None, user=None, mode=DEFAULT_MODE, model=None):
    """ход агента. возвращает (ответ, токенов). ошибки не валят ход"""
    user = user or {}
    cfg = md(mode)
    # если юзер выбрал конкретную модель — она главнее режима,
    # но тулы/скиллы/зрение берём из режима
    model = str(model or "").strip()
    if model and model in MODEL_IDS:
        if model != cfg["model"]:
            cfg = dict(cfg)
            cfg["model"] = model
            # у выбранной модели может не быть своего зрения — тогда опишем отдельной
            cfg["vision"] = None if model in NATIVE_VISION else (cfg.get("vision") or "gemini-3.8-flash")
    images = images or []

    # зрение: если модель не видит сама — описываем отдельной моделью
    vision_note = ""
    native_imgs = []
    if images:
        if cfg["vision"]:
            on_event({"t": "status", "d": "смотрю фото"})
            try:
                import vision
                vision_note = await vision.describe_photos(images, model=cfg["vision"])
            except Exception as e:
                log.warning("зрение упало: %s", e)
                vision_note = "[картинку разобрать не вышло]"
        else:
            native_imgs = _image_parts(images)

    log.info("ход: режим=%s модель=%s тулы=%s скиллы=%s зрение=%s",
             norm_mode(mode), cfg["model"], cfg["tools"], cfg["tools"], cfg["vision"] or "нативное")
    _emit = on_event

    def on_event(e):            # noqa: F811 — копим ход мыслей и пропускаем дальше
        if e.get("t") == "reason":
            thought_parts.append(str(e.get("d") or ""))
        _emit(e)

    tools = Tools(user=user, skills=cfg["tools"])
    # шпаргалку тянем только когда вопрос похож на школьную задачу
    ask = ""
    for _m in reversed((history or [])[-4:]):
        if (_m.get("role") or "") == "user" and _m.get("content"):
            ask = str(_m["content"])
            break
    messages = build_system(user, mode, vision_note, ask, cfg["model"])

    hist = (history or [])[-MAX_HISTORY:]
    for i, m in enumerate(hist):
        role = m.get("role")
        if role not in ("user", "assistant") or not m.get("content"):
            continue
        last = (i == len(hist) - 1)
        if last and role == "user" and native_imgs:
            messages.append({"role": "user", "content": [{"type": "text", "text": m["content"]}] + native_imgs})
        else:
            messages.append({"role": role, "content": m["content"]})
    if native_imgs and not messages[-1:]:
        messages.append({"role": "user", "content": [{"type": "text", "text": "вот картинка"}] + native_imgs})

    deadline = time.time() + BUDGET_SECONDS
    answer_parts, total, thought_parts, attached, sites = [], 0, [], [], []
    models = [cfg["model"]] + [m for m in FALLBACK_MODELS if m != cfg["model"]]
    last_err = ""
    image_failed = [False]   # все модели упали именно из-за картинки -> уходим в разбор фото отдельной моделью
    seen_answer = [False]    # уже был текст (и тулы поверх), чтобы не подменять часть работы описанием фото

    step_limit = MAX_ITER * STEP_BURST
    for step in range(step_limit):
        # порция шагов кончилась, а задача живая: не бросаем, говорим «продолжаю» и работаем дальше
        if step and step % MAX_ITER == 0:
            on_event({"t": "status", "d": "продолжаю"})
            messages.append({"role": "user",
                             "content": "шаги продлены. продолжай эту же задачу с того места, где "
                                        "остановился, и доведи её до конца, не переспрашивая заново"})
        if time.time() > deadline:
            on_event({"t": "error", "d": "время хода вышло"})
            break
        on_event({"t": "status", "d": "думает" if step == 0 else "работает"})

        # последний рубеж: если все модели упали на картинке — отвечаем по описанию
        # от vision-модели, а не молчим (так ломалось у кентов на больших png)
        if step == 0 and images and image_failed[0] and not seen_answer[0]:
            try:
                import vision
                on_event({"t": "status", "d": "смотрю фото отдельной моделью"})
                note = await vision.describe_photos(images)
                history = list(history or []) + [
                    {"role": "system", "content": "человек прислал картинку, вот что на ней "
                                                  "(это твои глаза, считай фактом):\n" + note}]
                messages = build_system(user, mode, note, ask, cfg["model"])
                for i, m in enumerate((history or [])[-MAX_HISTORY:]):
                    role = m.get("role")
                    if role not in ("user", "assistant", "system") or not m.get("content"):
                        continue
                    messages.append({"role": role, "content": m["content"]})
                native_imgs = []
                image_failed[0] = False
                on_event({"t": "status", "d": "отвечаю по фото"})
                continue
            except Exception as e:
                log.warning("разбор фото упал: %s", e)

        content, calls, err, used = "", [], None, 0
        for model in models:
            trial = dict(cfg)
            trial["model"] = model
            log.info("режим %s: зову модель %s (тулы=%s, план=%s)",
                     norm_mode(mode), model, trial["tools"], trial["plan"])
            content, calls, err, used = await one_call(trial, messages, on_event, deadline, model=model)
            total += used
            if err is None:
                break
            last_err = err
            # 503/4xx на картинке у всех моделей — не тупим, дальше разберём фото отдельно
            if native_imgs and ("http 5" in str(err) or "http 4" in str(err)):
                image_failed[0] = True
            log.warning("модель %s: %s", model, err)
            if len(models) > 1:
                on_event({"t": "status", "d": "пробую другую модель"})
            await asyncio.sleep(1)

        # если все платные модели упали — пробуем бесплатные
        if err is not None or (err is None and not content):
            on_event({"t": "status", "d": "переключение на фри"})
            for model in FREE_FALLBACKS:
                if model == cfg["model"]:
                    continue
                trial = dict(cfg)
                trial["model"] = model
                log.info("режим %s: зову фри модель %s", norm_mode(mode), model)
                content, calls, err, used = await one_call(trial, messages, on_event, deadline, model=model)
                total += used
                if err is None:
                    break
                log.warning("фри модель %s: %s", model, err)
                await asyncio.sleep(1)

        content = (content or "").strip()
        if not calls:
            if content:
                answer_parts.append(content)
                seen_answer[0] = True
                break
            if err:
                on_event({"t": "error", "d": "модель не ответила: " + last_err})
                break
            # пусто при непустом расходе = размышления съели лимит. даём запас и повторяем
            if used and used > 0 and step == 0:
                cfg["max_tokens"] = min(16000, int(cfg["max_tokens"]) * 2)
                on_event({"t": "status", "d": "думает глубже"})
                messages.append({"role": "user", "content": "ответь собеседнику текстом, коротко"})
                continue
            messages.append({"role": "user", "content": "ответь собеседнику текстом"})
            continue

        messages.append({
            "role": "assistant", "content": content,
            "tool_calls": [{"id": c["id"], "type": "function",
                            "function": {"name": c["name"], "arguments": c["args_raw"] or "{}"}}
                           for c in calls],
        })
        if content:
            answer_parts.append(content)
            seen_answer[0] = True

        for c in calls:
            try:
                args = json.loads(c["args_raw"] or "{}", strict=False)
            except Exception:
                args = {}
            on_event({"t": "tool", "name": c["name"], "args": short(args)})
            t0 = time.time()
            try:
                result = await tools.execute(c["name"], args)
            except Exception as e:
                log.exception("тул %s упал", c["name"])
                result = {"error": "%s: %s" % (type(e).__name__, e)}
            took = round(time.time() - t0, 1)
            ok = not (isinstance(result, dict) and result.get("error"))
            on_event({"t": "tool_done", "name": c["name"], "ok": ok, "took": took,
                      "out": short_out(result)})
            if c["name"] == "attach_file" and isinstance(result, dict) and not result.get("error"):
                on_event({"t": "attach", "name": result.get("name"), "url": result.get("url"),
                          "kind": result.get("kind"), "caption": result.get("caption") or ""})
                attached.append({k: result.get(k) for k in ("name", "url", "kind", "caption")})
            if c["name"] == "publish_site" and isinstance(result, dict) and not result.get("error"):
                on_event({"t": "site", "slug": result.get("slug"), "url": result.get("url")})
                sites.append({"slug": result.get("slug"), "url": result.get("url")})
            try:
                blob = json.dumps(result, ensure_ascii=False)[:12000]
            except Exception:
                blob = str(result)[:12000]
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": blob})

    text = "\n\n".join(p for p in answer_parts if p).strip()
    if not text:
        if last_err:
            text = "не получилось ответить: " + last_err[:200]
        elif step >= step_limit - 1:
            text = "упёрся в потолок шагов (это очень много). скажи проще или раздели на части, добью дальше"
        else:
            text = "модель ушла в размышления и не выдала ответ. повтори или смени режим на медиум"  
    meta = {"model": cfg["model"], "mode": norm_mode(mode),
            "thought": (thought_parts or "")[-8000:]}
    if attached:
        meta["attached"] = attached[:6]
    if sites:
        meta["sites"] = sites[:4]
    on_event({"t": "done", "answer": text, "tokens": total, "meta": meta})
    return text, total, meta


def short(args):
    out = {}
    for k, v in (args or {}).items():
        s = str(v)
        out[k] = s if len(s) <= 600 else s[:600] + "…"
    return out


def short_out(result):
    try:
        s = json.dumps(result, ensure_ascii=False)
    except Exception:
        s = str(result)
    return s if len(s) <= 1500 else s[:1500] + "…"
