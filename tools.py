"""тулы агента: сервер, файлы, поиск, скиллы, память"""
import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path

import httpx

import memory
from config import (
    MAX_BASH_OUT,
    MAX_BASH_SECONDS,
    MAX_PROMPT_LEN,
    MAX_TOOL_OUT,
    NOTES_DIR,
    PROMPT_FILE,
    SCHOOL_FILE,
    SEARCH_URL,
    SHARE_BASE,
    SHARE_DIR,
    SKILLS_DIR,
    WORK_DIR,
)

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"


_SCHOOL_HINT = re.compile(
    r"задач|уравнен|неравенств|формул|реш(и|ать|ение)|вычисл|пример|"
    r"контрольн|самостоят|егэ|огэ|экзамен|теорем|дроб|производн|интеграл|"
    r"логарифм|тригонометр|синус|косинус|учебник|школ|класс|физик|хими|"
    r"геометри|алгебр|русск(ий|ого) язык|сочинени|изложени|истори|обществозн",
    re.I)


def wants_school(text):
    """похоже что просят школьную задачу — только тогда тянем шпаргалку"""
    return bool(_SCHOOL_HINT.search(text or ""))


def load_prompt(with_school=False):
    """промт, и шпаргалка к нему только если задача похожа на школьную"""
    text = PROMPT_FILE.read_text()
    marker = "--- ШПАРГАЛКА ---"
    if not with_school:
        return text.replace(marker, "", 1).rstrip()
    school = SCHOOL_FILE.read_text() if SCHOOL_FILE.exists() else ""
    out = text.replace(marker, school, 1) if marker in text else text + "\n\n" + school
    if len(out) > MAX_PROMPT_LEN:
        out = text.replace(marker, "", 1)
    return out



_skill_cache = {"t": 0, "items": []}


def _skill_desc(path: Path):
    """имя и описание из frontmatter SKILL.md"""
    try:
        head = path.read_text(errors="replace")[:1500]
    except Exception:
        return None
    name = path.parent.name
    desc = ""
    m = re.search(r"^---\s*\n(.*?)\n---", head, re.S)
    if m:
        fm = m.group(1)
        n = re.search(r"^name:\s*(.+)$", fm, re.M)
        d = re.search(r"^description:\s*(.+)$", fm, re.M)
        if n:
            name = n.group(1).strip().strip('"\'')
        if d:
            desc = d.group(1).strip().strip('"\'')
    if not desc:
        body = re.sub(r"^---.*?---", "", head, flags=re.S).strip()
        desc = body.split("\n", 1)[0][:200]
    return {"name": name, "desc": desc, "path": str(path)}


def skills_scan(force=False):
    now = time.time()
    if not force and _skill_cache["items"] and now - _skill_cache["t"] < 300:
        return _skill_cache["items"]
    items = []
    for p in sorted(SKILLS_DIR.rglob("SKILL.md")):
        d = _skill_desc(p)
        if d:
            items.append(d)
    _skill_cache["items"] = items
    _skill_cache["t"] = now
    return items



async def web_search(query, count=8):
    """сначала свой searxng, если не поднят — дакдак"""
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}) as c:
            r = await c.get(SEARCH_URL, params={"q": query, "format": "json", "language": "ru"})
        if r.status_code == 200:
            data = r.json()
            out = []
            for it in (data.get("results") or [])[:count]:
                out.append({"title": (it.get("title") or "")[:200],
                            "url": it.get("url"),
                            "snippet": (it.get("content") or "")[:300]})
            if out:
                return {"source": "searxng", "results": out}
    except Exception:
        pass
    return await _ddg(query, count)


async def _ddg(query, count=8):
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA}, follow_redirects=True) as c:
            r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
        results = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
        items = []
        for i, (url, title) in enumerate(results[:count]):
            title = re.sub(r"<[^>]+>", "", title)
            snip = re.sub(r"<[^>]+>", "", snippets[i]) if i < len(snippets) else ""
            if "uddg=" in url:
                import urllib.parse

                url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
            items.append({"title": title.strip(), "url": url, "snippet": snip.strip()[:300]})
        return {"source": "duckduckgo", "results": items}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def web_fetch(url):
    try:
        if not url.startswith("http"):
            url = "https://" + url
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}, follow_redirects=True) as c:
            r = await c.get(url)
        html = r.text
        html = re.sub(r"(?s)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", "", html)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;|&#\d+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"status": r.status_code, "length": len(text), "text": text[:MAX_TOOL_OUT]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def run_bash(command, timeout=120):
    timeout = max(1, min(int(timeout or 120), MAX_BASH_SECONDS))
    try:
        p = await asyncio.create_subprocess_shell(
            command, cwd=str(WORK_DIR),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
        text = out.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        return {"error": f"таймаут {timeout}с"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if len(text) > MAX_BASH_OUT:
        text = text[:MAX_BASH_OUT] + "\n...обрезано"
    return {"exit_code": p.returncode, "output": text}


def _safe_path(path, must_exist=False, guest=False):
    """путь внутри рабочей зоны. ограничений по путям нет: владелец доверяет всем юзерам"""
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = WORK_DIR / p
    if must_exist and not p.exists():
        return None, f"нет такого пути: {p}"
    return p, None


def read_file(path, offset=1, limit=400, guest=False):
    p, err = _safe_path(path, must_exist=True)
    if err:
        return {"error": err}
    if p.is_dir():
        return {"error": "это папка, юзай list_dir"}
    try:
        data = p.read_bytes()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if b"\x00" in data[:2048]:
        return {"error": f"бинарный файл, {len(data)} байт"}
    lines = data.decode(errors="replace").splitlines()
    offset = max(1, int(offset or 1))
    limit = max(1, min(int(limit or 400), 4000))
    chunk = lines[offset - 1: offset - 1 + limit]
    return {"path": str(p), "total_lines": len(lines), "from": offset,
            "content": "\n".join(f"{i}|{l}" for i, l in enumerate(chunk, start=offset))}


def write_file(path, content):
    p, err = _safe_path(path)
    if err:
        return {"error": err}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > 0:
            bak = p.with_name(p.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(p, bak)
        p.write_text(content)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"status": "записано", "path": str(p), "bytes": len(content.encode())}


def edit_file(path, old, new, replace_all=False):
    p, err = _safe_path(path, must_exist=True)
    if err:
        return {"error": err}
    try:
        text = p.read_text()
        if old not in text:
            return {"error": "не нашёл такой кусок"}
        cnt = text.count(old)
        if cnt > 1 and not replace_all:
            return {"error": f"кусок встречается {cnt} раз, уточни или replace_all=true"}
        bak = p.with_name(p.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(p, bak)
        p.write_text(text.replace(old, new, -1 if replace_all else 1))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"status": "правка внесена", "path": str(p), "замен": cnt}


def list_dir(path=".", guest=False):
    p, err = _safe_path(path, must_exist=True)
    if err:
        return {"error": err}
    if not p.is_dir():
        return {"error": "это файл"}
    items = []
    for f in sorted(p.iterdir())[:200]:
        try:
            if f.is_dir():
                items.append({"name": f.name + "/", "type": "dir"})
            else:
                items.append({"name": f.name, "type": "file", "kb": round(f.stat().st_size / 1024, 1)})
        except Exception:
            pass
    return {"path": str(p), "items": items}


def share_file(path, note="", guest=False):
    from urllib.parse import quote

    p, err = _safe_path(path, must_exist=True)
    if err:
        return {"error": err}
    if not p.is_file():
        return {"error": "не файл"}
    try:
        SHARE_DIR.mkdir(parents=True, exist_ok=True)
        target = SHARE_DIR / p.name
        if target.exists() and target.resolve() != p.resolve():
            target = SHARE_DIR / f"{p.stem}_{time.strftime('%Y%m%d-%H%M%S')}{p.suffix}"
        if target.resolve() != p.resolve():
            if p.stat().st_size > 10 * 1024 * 1024:
                shutil.copy2(p, target)
            else:
                target.write_bytes(p.read_bytes())
    except Exception as e:
        return {"error": f"не скопировалось: {type(e).__name__}: {e}"}
    return {"file": target.name, "mb": round(target.stat().st_size / 1048576, 2),
            "url": SHARE_BASE + quote(target.name), "note": note,
            "hint": "ссылка вечная, живёт пока жив файл"}


ATTACH_DIR = Path(os.environ.get("AI_ATTACH_DIR", "/srv/agent/data/attach"))


def attach_file(path, caption="", guest=False):
    """файл или картинка прямо в чат: копия в каталог вложений + ссылка"""
    from urllib.parse import quote

    p, err = _safe_path(path, must_exist=True)
    if err:
        return {"error": err}
    if not p.is_file():
        return {"error": "не файл"}
    if p.stat().st_size > 64 * 1024 * 1024:
        return {"error": "файл больше 64мб"}
    try:
        ATTACH_DIR.mkdir(parents=True, exist_ok=True)
        target = ATTACH_DIR / p.name
        if target.exists() and target.resolve() != p.resolve():
            target = ATTACH_DIR / f"{p.stem}_{time.strftime('%H%M%S')}{p.suffix}"
        if target.resolve() != p.resolve():
            shutil.copy2(p, target)
    except Exception as e:
        return {"error": f"не скопировалось: {type(e).__name__}: {e}"}
    kind = "image" if re.search(r"\.(png|jpe?g|gif|webp|avif|bmp|svg)$", p.name, re.I) else "file"
    return {"name": target.name, "kind": kind, "caption": caption,
            "mb": round(target.stat().st_size / 1048576, 2),
            "url": "/attach/" + quote(target.name),
            "hint": "вложение уже показано человеку в чате"}


SITES_DIR = Path("/var/www/sites")
SITE_TPL = Path(os.environ.get("AI_SITE_TPL", "/srv/agent/app/site_tpl.html"))


def publish_site(name, html, title=""):
    """выложить статичную страницу на поддомен"""
    slug = re.sub(r"[^a-z0-9-]", "", str(name or "").strip().lower())
    if not slug or len(slug) > 32:
        return {"error": "имя: только латиница, цифры и дефис, до 32 символов"}
    if not html or len(html) < 50:
        return {"error": "страница подозрительно пустая"}
    if len(html) > 3 * 1024 * 1024:
        return {"error": "страница больше 3мб, сделай легче"}
    low = html.lower()
    if "<script" in low and "src=\"http" in low:
        return {"error": "внешние скрипты не нужны, собери страницу самодостаточной"}
    if re.search(r"\b(fetch|xmlhttprequest|websocket)\s*\(", low):
        return {"error": "страница должна быть статичной, без запросов к сети"}
    d = SITES_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    conf = "/etc/nginx/sites-available/site-" + slug
    root = str(d)
    nginx = (
        "server {\n"
        "    listen 80;\n"
        "    listen [::]:80;\n"
        "    server_name %s.example.com;\n"
        "    root %s;\n"
        "    index index.html;\n"
        "    add_header X-Robots-Tag \"noindex, noarchive, nosnippet\" always;\n"
        "    location / { try_files $uri $uri/ =404; }\n"
        "}\n" % (slug, root))
    Path(conf + ".tmp").write_text(nginx, encoding="utf-8")
    return {"slug": slug, "dir": root, "conf_tmp": conf + ".tmp", "conf_final": conf,
            "title": title, "url": "https://%s.example.com" % slug,
            "next": "нужно: cp conf_tmp conf_final, ln -s в sites-enabled, nginx -t, reload, "
                    "создать dns-запись в cloudflare (a 192.0.2.1, proxied), "
                    "выпустить сертификат certbot --nginx -d %s.example.com" % slug}


async def _sh(cmd, timeout=180):
    p = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        p.kill()
        return 124, "таймаут"
    return p.returncode or 0, out.decode("utf-8", "replace")[-4000:]


CF_TOKEN_FILE = Path(os.environ.get("AI_CF_ENV", "/srv/agent/app/cloudflare.env"))


def _cf_upsert_dns(slug):
    """создать A-запись slug.example.com -> 192.0.2.1 через cloudflare api"""
    import urllib.request as urlreq

    tok = ""
    try:
        for line in CF_TOKEN_FILE.read_text().splitlines():
            if line.strip().startswith("CF_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"')
    except Exception:
        return {"error": "нет cloudflare.env с токеном"}
    if not tok:
        return {"error": "пустой CF_API_TOKEN"}
    hdr = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
    base = "https://api.cloudflare.com/client/v4"
    name = slug + ".example.com"
    try:
        req = urlreq.Request(base + "/zones?name=example.com", headers=hdr)
        z = json.loads(urlreq.urlopen(req, timeout=60).read())
        if not z.get("success") or not z.get("result"):
            return {"error": "зона не нашлась", "detail": z.get("errors")}
        zid = z["result"][0]["id"]
        req = urlreq.Request(base + f"/zones/{zid}/dns_records?name={name}", headers=hdr)
        ex = json.loads(urlreq.urlopen(req, timeout=60).read())
        body = json.dumps({"type": "A", "name": name, "content": "192.0.2.1",
                           "ttl": 1, "proxied": True}).encode()
        if ex.get("result"):
            rid = ex["result"][0]["id"]
            req = urlreq.Request(base + f"/zones/{zid}/dns_records/{rid}", data=body,
                                 headers=hdr, method="PUT")
            act = "обновил"
        else:
            req = urlreq.Request(base + f"/zones/{zid}/dns_records", data=body,
                                 headers=hdr, method="POST")
            act = "создал"
        r = json.loads(urlreq.urlopen(req, timeout=60).read())
        if not r.get("success"):
            return {"error": "dns не записался", "detail": r.get("errors")}
        return {"status": act, "name": name}
    except Exception as e:
        return {"error": f"cloudflare: {type(e).__name__}: {e}"}


async def deploy_site(info):
    """выкатить готовую страницу: nginx, dns, сертификат"""
    slug = info["slug"]
    steps = []
    code, out = await _sh(f"mv -f {info['conf_tmp']} {info['conf_final']}")
    steps.append(("конфиг", code, out[:200]))
    if code:
        return {"error": "не лёг конфиг nginx", "steps": steps}
    await _sh(f"ln -sfn {info['conf_final']} /etc/nginx/sites-enabled/site-{slug}")
    code, out = await _sh("nginx -t")
    steps.append(("проверка", code, out[:300]))
    if code:
        await _sh(f"rm -f /etc/nginx/sites-enabled/site-{slug}")
        return {"error": "nginx не принял конфиг, откатил", "steps": steps}
    code, out = await _sh("systemctl reload nginx")
    steps.append(("перезагрузка nginx", code, out[:200]))
    dns = _cf_upsert_dns(slug)
    steps.append(("dns", 0 if not dns.get("error") else 1, json.dumps(dns, ensure_ascii=False)[:200]))
    if dns.get("error"):
        return {"error": "сайт поднят, но dns не записался", "url": info["url"],
                "steps": steps, "dns": dns}
    await asyncio.sleep(6)
    code, out = await _sh(
        f"certbot --nginx -d {slug}.example.com --non-interactive --agree-tos "
        f"--register-unsafely-without-email --redirect", timeout=180)
    steps.append(("сертификат", code, out[-400:]))
    ok = code == 0
    return {"status": "сайт живой" if ok else "сайт поднят, сертификат не вышел",
            "url": info["url"], "slug": slug, "https": ok,
            "hint": "ссылка постоянная, пока жив файл", "steps": steps}


def list_shared():
    from urllib.parse import quote

    try:
        items = []
        for f in sorted(SHARE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
            if f.is_file():
                items.append({"name": f.name, "mb": round(f.stat().st_size / 1048576, 2),
                              "url": SHARE_BASE + quote(f.name)})
        return {"files": items, "total": len(items)}
    except Exception as e:
        return {"error": str(e)}


def save_note(name, text):
    try:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60] or "note"
        p = NOTES_DIR / (safe if safe.endswith(".md") else safe + ".md")
        with p.open("a") as f:
            f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}\n{text}\n")
        return {"saved": str(p)}
    except Exception as e:
        return {"error": str(e)}


def get_tool_schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": "run_bash",
                "description": "выполнить bash команду в рабочей папке. для арифметики и расчётов обязательно считай python3 кодом, не в уме. "
                               "критичные сервисы без явной просьбы не трогать",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "description": "секунды, максимум 600, по умолчанию 120"},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "прочитать текстовый файл (с номерами строк). можно пагинировать offset/limit",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "абсолютный путь или относительно рабочей папки"},
                        "offset": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "записать файл целиком (старое содержимое уйдёт в .bak). для правок существующего лучше edit_file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "заменить кусок текста в файле. старый файл сохраняется в .bak",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string", "description": "что заменить, уникальный кусок"},
                        "new": {"type": "string", "description": "на что заменить"},
                        "replace_all": {"type": "boolean"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "посмотреть что лежит в папке",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "поиск в интернете. даёт заголовки ссылки и снипеты",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "count": {"type": "integer"}},
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "скачать страницу по url и вытащить из неё текст",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skills_index",
                "description": "список доступных скиллов (методичек) с описаниями. ищи тут перед тем как делать что-то сложное",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "фильтр по словам, пусто = весь список"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "skill_view",
                "description": "прочитать скилл целиком по имени из skills_index",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "запомнить факт о шпателе или важное навсегда",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "tag": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "вспомнить сохранённые факты",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "forget",
                "description": "удалить факт по id",
                "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_prompt",
                "description": "прочитать свой текущий системный промт",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_prompt",
                "description": "заменить основную часть своего промта целиком (шпаргалка school.md отдельно). применится со следующего сообщения",
                "parameters": {
                    "type": "object",
                    "properties": {"new_prompt": {"type": "string"}},
                    "required": ["new_prompt"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "attach_file",
                "description": "приложить файл или картинку прямо в чат: человек увидит вложение и ссылку на скачивание. картинки показываются превью. бери любой файл со сервера",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "путь к файлу на сервере"},
                                   "caption": {"type": "string", "description": "подпись"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "publish_site",
                "description": "собрать статичную страницу и выложить на поддомен, вернуть ссылку. html целиком одной строкой, без внешних скриптов и запросов к сети",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "description": "имя поддомена: латиница, цифры, дефис"},
                                   "html": {"type": "string", "description": "полный html страницы"},
                                   "title": {"type": "string", "description": "заголовок для человека"}},
                    "required": ["name", "html"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "share_file",
                "description": "положить файл в общий склад и получить вечную ссылку для человека",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "note": {"type": "string"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_shared",
                "description": "что лежит в общем складе файлов",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_note",
                "description": "дописать заметку в свои заметки на сервере",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["name", "text"],
                },
            },
        },
    ]


class Tools:
    """исполнение тулов. ограничений для не-овнеров нет: владелец доверяет всем"""

    OWNER_ONLY = set()

    def __init__(self, user=None, skills=True):
        self.user = user or {}
        self.is_owner = bool(self.user.get("is_owner"))
        self.skills_on = bool(skills)

    async def execute(self, name, args):
        if not self.is_owner and name in self.OWNER_ONLY:
            return {"error": "это делает только шпатель. попроси его"}
        fn = getattr(self, f"tool_{name}", None)
        if fn is None:
            return {"error": f"нет такого тула {name}"}
        try:
            res = fn(**args)
            if asyncio.iscoroutine(res):
                res = await res
            if isinstance(res, (dict, list)):
                s = json.dumps(res, ensure_ascii=False)
                if len(s) > MAX_TOOL_OUT:
                    res = {"truncated": True, "head": s[:MAX_TOOL_OUT]}
            return res
        except TypeError as e:
            return {"error": f"кривые аргументы для {name}: {e}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    async def tool_run_bash(self, command, timeout=None):
        return await run_bash(command, timeout or 120)

    def tool_read_file(self, path, offset=1, limit=400):
        return read_file(path, offset, limit)

    def tool_write_file(self, path, content):
        return write_file(path, content)

    def tool_edit_file(self, path, old, new, replace_all=False):
        return edit_file(path, old, new, replace_all)

    def tool_list_dir(self, path="."):
        return list_dir(path)

    async def tool_web_search(self, query, count=8):
        return await web_search(query, count)

    async def tool_web_fetch(self, url):
        return await web_fetch(url)

    def tool_skills_index(self, query=""):
        if not self.skills_on:
            return {"total": 0, "skills": [], "note": "в этом режиме скиллы выключены"}
        items = skills_scan()
        if query:
            words = [w.lower() for w in re.split(r"\s+", query) if w]
            items = [i for i in items
                     if any(w in (i["name"] + " " + i["desc"]).lower() for w in words)]
        return {"total": len(items),
                "skills": [{"name": i["name"], "desc": i["desc"][:180]} for i in items[:60]]}

    def tool_skill_view(self, name):
        if not self.skills_on:
            return {"error": "в этом режиме скиллы выключены"}
        key = (name or "").strip().lower()
        for i in skills_scan():
            if i["name"].lower() == key or Path(i["path"]).parent.name.lower() == key:
                text = Path(i["path"]).read_text(errors="replace")
                return {"name": i["name"], "path": i["path"], "content": text[:MAX_TOOL_OUT]}
        cands = [i for i in skills_scan() if key and key in i["name"].lower()]
        if len(cands) == 1:
            text = Path(cands[0]["path"]).read_text(errors="replace")
            return {"name": cands[0]["name"], "path": cands[0]["path"], "content": text[:MAX_TOOL_OUT]}
        return {"error": "не нашёл", "похожие": [c["name"] for c in cands[:10]]}

    def tool_remember(self, text, tag=""):
        return memory.remember(text, tag, uid=self.user.get("id", 0))

    def tool_recall(self, query=""):
        rows = memory.recall(query, uid=self.user.get("id", 0))
        return {"facts": rows} if rows else {"note": "ничего не найдено"}

    def tool_forget(self, id):
        return memory.forget(id, uid=self.user.get("id", 0))

    def tool_read_prompt(self):
        return {"prompt": load_prompt()}

    def tool_edit_prompt(self, new_prompt):
        new_prompt = (new_prompt or "").strip()
        if len(new_prompt) < 200:
            return {"error": "промт подозрительно короткий, не буду портить"}
        if len(new_prompt) > 18000:
            return {"error": f"слишком длинный {len(new_prompt)}, лимит 18000"}
        bak = PROMPT_FILE.with_name("prompt.md.bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(PROMPT_FILE, bak)
        PROMPT_FILE.write_text(new_prompt + "\n")
        return {"status": "промт обновлён, применится со следующего сообщения", "bak": str(bak)}

    def tool_attach_file(self, path, caption=""):
        return attach_file(path, caption)

    async def tool_publish_site(self, name, html, title=""):
        res = publish_site(name, html, title)
        if res.get("error"):
            return res
        return await deploy_site(res)

    def tool_share_file(self, path, note=""):
        return share_file(path, note)

    def tool_list_shared(self):
        return list_shared()

    def tool_save_note(self, name, text):
        return save_note(name, text)
