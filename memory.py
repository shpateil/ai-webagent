"""данные агента: пользователи, чаты, память. один писатель, WAL, устойчивость к кривым строкам"""
import hashlib
import hmac
import json
import os
import sqlite3
import time

from config import DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  login TEXT UNIQUE NOT NULL,
  phash TEXT NOT NULL,
  pname TEXT DEFAULT '',
  is_owner INTEGER DEFAULT 0,
  disabled INTEGER DEFAULT 0,
  created REAL
);
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT 0,
  text TEXT NOT NULL, tag TEXT DEFAULT '', created REAL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, val TEXT);
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER DEFAULT 0,
  title TEXT DEFAULT '', created REAL, updated REAL,
  mode TEXT DEFAULT 'max'
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER NOT NULL, role TEXT NOT NULL,
  content TEXT DEFAULT '', meta TEXT DEFAULT '', created REAL,
  tokens INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id, id);
CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, updated);
"""


def _db():
    c = sqlite3.connect(DB_FILE, timeout=20, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=15000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


_ready = False


def init():
    """схема и миграции один раз при старте"""
    global _ready
    c = _db()
    c.executescript(SCHEMA)
    for stmt in ("ALTER TABLE facts ADD COLUMN user_id INTEGER DEFAULT 0",
                 "ALTER TABLE chats ADD COLUMN user_id INTEGER DEFAULT 0",
                 "ALTER TABLE messages ADD COLUMN tokens INTEGER DEFAULT 0",
                 "ALTER TABLE chats ADD COLUMN mode TEXT DEFAULT 'max'",
                 "ALTER TABLE users ADD COLUMN mode TEXT DEFAULT 'max'",
                 "ALTER TABLE users ADD COLUMN model TEXT DEFAULT ''"):
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass
    c.close()
    _ready = True


def hash_password(pw):
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", str(pw).encode(), salt, 120_000)
    return salt.hex() + "$" + h.hex()


def verify_password(pw, stored):
    try:
        salt_hex, h_hex = str(stored or "").split("$", 1)
        h = hashlib.pbkdf2_hmac("sha256", str(pw).encode(), bytes.fromhex(salt_hex), 120_000)
        return hmac.compare_digest(h.hex(), h_hex)
    except Exception:
        return False


def user_by_login(login):
    c = _db()
    r = c.execute("SELECT * FROM users WHERE login=? COLLATE NOCASE", (str(login).strip(),)).fetchone()
    c.close()
    return dict(r) if r else None


def user_by_id(uid):
    try:
        uid = int(uid)
    except Exception:
        return None
    c = _db()
    r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return dict(r) if r else None


def list_users():
    c = _db()
    rows = c.execute(
        "SELECT u.id, u.login, u.pname, u.is_owner, u.disabled, u.created,"
        " (SELECT COUNT(*) FROM chats c WHERE c.user_id=u.id) AS chats,"
        " (SELECT COALESCE(SUM(m.tokens),0) FROM messages m JOIN chats c2 ON c2.id=m.chat_id"
        "   WHERE c2.user_id=u.id) AS tokens,"
        " (SELECT COUNT(*) FROM messages m2 JOIN chats c3 ON c3.id=m2.chat_id"
        "   WHERE c3.user_id=u.id AND m2.role='user') AS total_msgs"
        " FROM users u ORDER BY u.is_owner DESC, u.id ASC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_user(login, password, pname="", is_owner=0, limit_day=100, web=1):
    login = str(login).strip()[:32]
    if not login:
        return {"error": "пустой логин"}
    c = _db()
    try:
        cols = "login, phash, pname, is_owner, created"
        vals = [login, hash_password(password), str(pname or login).strip()[:40],
                int(is_owner), time.time()]
        have = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "limit_day" in have:
            cols += ", limit_day"
            vals.append(int(limit_day or 100))
        if "web" in have:
            cols += ", web"
            vals.append(1 if web else 0)
        cur = c.execute("INSERT INTO users (" + cols + ") VALUES (" + ",".join("?" * len(vals)) + ")", vals)
        uid = cur.lastrowid
    except sqlite3.IntegrityError:
        c.close()
        return {"error": "такой логин уже есть"}
    except Exception as e:
        c.close()
        return {"error": "%s: %s" % (type(e).__name__, e)}
    c.close()
    return {"id": uid, "login": login}


def set_password(uid, password):
    c = _db()
    c.execute("UPDATE users SET phash=? WHERE id=?", (hash_password(password), int(uid)))
    c.close()
    return {"ok": True}


def set_user(uid, **fields):
    """правка полей юзера владельцем"""
    allowed = {"pname": str, "disabled": int}
    sets, vals = [], []
    for k, cast in allowed.items():
        if k in fields and fields[k] is not None:
            try:
                casted = cast(fields[k])
            except Exception:
                continue
            sets.append(k + "=?")
            vals.append(casted)
    if not sets:
        return {"ok": True}
    c = _db()
    c.execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", vals + [int(uid)])
    c.close()
    return {"ok": True}


def set_disabled(uid, val):
    c = _db()
    c.execute("UPDATE users SET disabled=? WHERE id=?", (1 if val else 0, int(uid)))
    c.close()
    return {"ok": True}


def delete_user(uid):
    uid = int(uid)
    c = _db()
    u = c.execute("SELECT is_owner FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        c.close()
        return {"error": "нет такого"}
    if u["is_owner"]:
        c.close()
        return {"error": "владельца удалить нельзя"}
    ids = [r["id"] for r in c.execute("SELECT id FROM chats WHERE user_id=?", (uid,)).fetchall()]
    if ids:
        q = ",".join("?" * len(ids))
        c.execute("DELETE FROM messages WHERE chat_id IN (" + q + ")", ids)
        c.execute("DELETE FROM chats WHERE id IN (" + q + ")", ids)
    c.execute("DELETE FROM facts WHERE user_id=?", (uid,))
    c.execute("DELETE FROM users WHERE id=?", (uid,))
    c.close()
    return {"ok": True}


def ensure_owner(login, password, pname="владелец"):
    """владелец есть всегда; его пароль всегда совпадает с тем что в .env"""
    init()
    u = user_by_login(login)
    if not u:
        add_user(login, password, pname, is_owner=1)
        u = user_by_login(login)
    if not verify_password(password, u["phash"]):
        set_password(u["id"], password)
    if not u["is_owner"]:
        c = _db()
        c.execute("UPDATE users SET is_owner=1 WHERE id=?", (u["id"],))
        c.close()
    return {"ok": True, "id": u["id"]}


def create_chat(title="", uid=0, mode="max"):
    now = time.time()
    c = _db()
    cur = c.execute("INSERT INTO chats (user_id, title, created, updated, mode) VALUES (?,?,?,?,?)",
                    (int(uid), str(title or "")[:80], now, now, str(mode or "max")))
    cid = cur.lastrowid
    c.close()
    return cid


def list_chats(limit=100, uid=None):
    c = _db()
    if uid is None:
        rows = c.execute("SELECT c.id, c.title, c.created, c.updated, c.mode,"
                         " (SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id) AS n"
                         " FROM chats c ORDER BY c.updated DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = c.execute("SELECT c.id, c.title, c.created, c.updated, c.mode,"
                         " (SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id) AS n"
                         " FROM chats c WHERE c.user_id=? ORDER BY c.updated DESC LIMIT ?",
                         (int(uid), limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def user_mode(uid):
    try:
        uid = int(uid)
    except Exception:
        return "max"
    c = _db()
    r = c.execute("SELECT mode FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return (r["mode"] if r and r["mode"] else "max")


def set_user_mode(uid, mode):
    c = _db()
    c.execute("UPDATE users SET mode=? WHERE id=?", (str(mode or "max")[:12], int(uid)))
    c.close()
    return {"ok": True}


def user_model(uid):
    """выбранная вручную модель, пусто = брать из режима"""
    try:
        uid = int(uid)
    except Exception:
        return ""
    c = _db()
    r = c.execute("SELECT model FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return (r["model"] if r and r["model"] else "")


def set_user_model(uid, model):
    c = _db()
    c.execute("UPDATE users SET model=? WHERE id=?", (str(model or "")[:40], int(uid)))
    c.close()
    return {"ok": True}


def chat_mode(cid):
    try:
        cid = int(cid)
    except Exception:
        return "max"
    c = _db()
    r = c.execute("SELECT mode FROM chats WHERE id=?", (cid,)).fetchone()
    c.close()
    return (r["mode"] if r and r["mode"] else "max")


def set_chat_mode(cid, mode):
    c = _db()
    c.execute("UPDATE chats SET mode=? WHERE id=?", (str(mode or "max")[:12], int(cid)))
    c.close()
    return {"ok": True}


def chat_owner(cid):
    try:
        cid = int(cid)
    except Exception:
        return None
    c = _db()
    r = c.execute("SELECT user_id FROM chats WHERE id=?", (cid,)).fetchone()
    c.close()
    return r["user_id"] if r else None


def rename_chat(cid, title):
    c = _db()
    c.execute("UPDATE chats SET title=? WHERE id=?", (str(title or "")[:80], int(cid)))
    c.close()


def delete_chat(cid):
    c = _db()
    c.execute("DELETE FROM messages WHERE chat_id=?", (int(cid),))
    c.execute("DELETE FROM chats WHERE id=?", (int(cid),))
    c.close()


def touch_chat(cid):
    c = _db()
    c.execute("UPDATE chats SET updated=? WHERE id=?", (time.time(), int(cid)))
    c.close()


def add_message(cid, role, content="", meta=None, tokens=0):
    c = _db()
    cur = c.execute("INSERT INTO messages (chat_id, role, content, meta, created, tokens)"
                    " VALUES (?,?,?,?,?,?)",
                    (int(cid), str(role), str(content or ""),
                     json.dumps(meta or {}, ensure_ascii=False), time.time(), int(tokens or 0)))
    mid = cur.lastrowid
    c.execute("UPDATE chats SET updated=? WHERE id=?", (time.time(), int(cid)))
    c.close()
    return mid


def _safe_meta(raw):
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def history(cid, limit=40):
    c = _db()
    rows = c.execute("SELECT id, role, content, created FROM messages WHERE chat_id=?"
                     " ORDER BY id DESC LIMIT ?", (int(cid), limit)).fetchall()
    c.close()
    out = [{"role": r["role"], "content": r["content"] or ""} for r in reversed(rows)]
    return out


def messages(cid, limit=500):
    c = _db()
    rows = c.execute("SELECT id, role, content, meta, created FROM messages WHERE chat_id=?"
                     " ORDER BY id DESC LIMIT ?", (int(cid), limit)).fetchall()
    c.close()
    out = []
    for r in reversed(rows):
        out.append({"id": r["id"], "role": r["role"], "content": r["content"] or "",
                    "meta": _safe_meta(r["meta"]), "created": r["created"]})
    return out


def drop_empty_chats():
    c = _db()
    cur = c.execute("DELETE FROM chats WHERE id NOT IN (SELECT DISTINCT chat_id FROM messages)")
    n = cur.rowcount
    c.close()
    return {"removed": n}


def remember(text, tag="", uid=0):
    c = _db()
    cur = c.execute("INSERT INTO facts (user_id, text, tag, created) VALUES (?,?,?,?)",
                    (int(uid), str(text), str(tag or ""), time.time()))
    c.close()
    return {"id": cur.lastrowid}


def recall(q="", limit=25, uid=0):
    c = _db()
    if q:
        rows = c.execute("SELECT id, text, tag FROM facts WHERE user_id=? AND text LIKE ?"
                         " ORDER BY id DESC LIMIT ?", (int(uid), f"%{q}%", limit)).fetchall()
    else:
        rows = c.execute("SELECT id, text, tag FROM facts WHERE user_id=? ORDER BY id DESC LIMIT ?",
                         (int(uid), limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def forget(fid, uid=0):
    c = _db()
    cur = c.execute("DELETE FROM facts WHERE id=? AND user_id=?", (int(fid), int(uid)))
    n = cur.rowcount
    c.close()
    return {"deleted": n}


def today_usage(uid):
    """сколько сообщений юзер отправил сегодня"""
    day = time.strftime("%Y-%m-%d")
    c = _db()
    r = c.execute("SELECT COUNT(*) AS n FROM messages m JOIN chats c2 ON c2.id=m.chat_id"
                  " WHERE c2.user_id=? AND m.role='user' AND m.created>=?",
                  (int(uid), _day_start())).fetchone()
    c.close()
    return r["n"] if r else 0


def _day_start():
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def usage_days(uid, days=30):
    """расход по дням: токены и сообщения, от старых к новым"""
    names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    out = []
    c = _db()
    for i in range(int(days) - 1, -1, -1):
        t = time.localtime(time.time() - i * 86400)
        start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
        r = c.execute(
            "SELECT COALESCE(SUM(m.tokens),0) AS tok,"
            " COALESCE(SUM(CASE WHEN m.role='user' THEN 1 ELSE 0 END),0) AS msgs"
            " FROM messages m JOIN chats c2 ON c2.id=m.chat_id"
            " WHERE c2.user_id=? AND m.created>=? AND m.created<?",
            (int(uid), start, start + 86400)).fetchone()
        out.append({"day": time.strftime("%d.%m", t), "dow": names[t.tm_wday],
                    "tokens": int(r["tok"] or 0), "msgs": int(r["msgs"] or 0)})
    c.close()
    return out


def usage_totals(uid):
    """итого за всё время и за сегодня"""
    c = _db()
    a = c.execute("SELECT COALESCE(SUM(m.tokens),0) AS tok, COUNT(*) AS n"
                  " FROM messages m JOIN chats c2 ON c2.id=m.chat_id WHERE c2.user_id=?",
                  (int(uid),)).fetchone()
    r = c.execute("SELECT COALESCE(SUM(m.tokens),0) AS tok, COALESCE(SUM(CASE WHEN m.role='user' THEN 1 ELSE 0 END),0) AS n"
              " FROM messages m JOIN chats c2 ON c2.id=m.chat_id"
              " WHERE c2.user_id=? AND m.created>=?",
              (int(uid), _day_start())).fetchone()
    c.close()
    return {"tokens": int(a["tok"] or 0), "msgs": int(a["n"] or 0),
            "today_tokens": int(r["tok"] or 0), "today_msgs": int(r["n"] or 0)}


def kv_get(key, default=""):
    c = _db()
    row = c.execute("SELECT val FROM kv WHERE key=?", (str(key),)).fetchone()
    c.close()
    return row["val"] if row else default


def kv_set(key, val):
    c = _db()
    c.execute("INSERT INTO kv (key,val) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",
              (str(key), str(val)))
    c.close()


def stats():
    c = _db()
    o = {
        "users": c.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"],
        "chats": c.execute("SELECT COUNT(*) AS n FROM chats").fetchone()["n"],
        "messages": c.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"],
        "tokens": c.execute("SELECT COALESCE(SUM(tokens),0) AS n FROM messages").fetchone()["n"],
    }
    c.close()
    return o
