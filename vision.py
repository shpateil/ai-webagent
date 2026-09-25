"""картинки: сжать и отправить модели с глазами (vision у deepseek-flash отключён)"""
import base64
import io
import logging
from pathlib import Path

import httpx

from config import CVC_KEY, IMAGE_TAIL, VISION_MODEL

log = logging.getLogger("vision")

VISION_URL = "https://ru.cheapvibecode.ru/v1/chat/completions"
MAX_EDGE = 1600
JPEG_Q = 80

VISION_SYS = (
    "тебе дали картинку из веб-чата. рассмотри её внимательно и опиши так,"
    " чтобы по описанию можно было решить задачу, не видя картинки.\n"
    "если это фото учебника или тетради с задачей: перепиши условие дословно,"
    " отдельно сохрани все числа, формулы (в виде latex), единицы измерения, буквы переменных."
    " если есть график, схема, чертёж или таблица — опиши что на них и какие значения.\n"
    "если это рукописный текст — перепиши его как есть.\n"
    "если это скриншот, код, интерфейс — перечисли что видно и весь важный текст дословно.\n"
    "если задача непонятна целиком — честно скажи что видно и чего не хватает.\n"
    "в конце последней строкой добавь: тип: <домашка|контрольная|тест|теория|скриншот|другое>,"
    " и если это задача ещё строку: предмет: <предмет>.\n"
    "без своих решений и рассуждений, максимум 250 слов"
)


def _to_data_url(data: bytes, mime: str):
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        scale = min(1.0, MAX_EDGE / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "сжат"
    except Exception as e:
        log.warning("pillow не смог: %s, шлём как есть", type(e).__name__)
        return "data:" + (mime or "image/jpeg") + ";base64," + base64.b64encode(data).decode(), "как есть"


async def _describe_one(data_url: str, caption: str, model: str = None) -> str:
    text = VISION_SYS if not caption else ("подпись человека к картинке: " + caption + "\n\n" + VISION_SYS)
    use_model = model or VISION_MODEL
    last = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    VISION_URL,
                    headers={"Authorization": "Bearer " + CVC_KEY, "Content-Type": "application/json"},
                    json={
                        "model": use_model,
                        "max_tokens": 1200,
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"type": "text", "text": text},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }],
                    },
                )
            if r.status_code == 200:
                out = (r.json()["choices"][0]["message"].get("content") or "").strip()
                if out:
                    log.info("фото описано моделью %s (%s симв)", use_model, len(out))
                    return out
                last = "пустой ответ"
            else:
                last = "http %s: %s" % (r.status_code, r.text[:120])
        except Exception as e:
            last = type(e).__name__
        log.warning("vision попытка %s не вышла: %s", attempt + 1, last)
    return "[картинку разобрать не вышло: %s]" % last


async def describe_photos(photos: list, model: str = None) -> str:
    """photos: список {'data': bytes, 'mime': str, 'caption': str, 'name': str}"""
    if not photos:
        return ""
    photos = photos[-IMAGE_TAIL:]
    parts = []
    for i, ph in enumerate(photos, 1):
        data_url, note = _to_data_url(ph["data"], ph.get("mime") or "image/jpeg")
        head = "[фото %s из %s, %s]" % (i, len(photos), ph.get("name") or "photo")
        if ph.get("caption"):
            head += " подпись: " + ph["caption"]
        desc = await _describe_one(data_url, ph.get("caption") or "", model=model)
        parts.append(head + "\n" + desc)
    return "\n\n".join(parts)


def save_upload(data: bytes, name: str, target_dir: Path):
    import re
    import time

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "file").name)[:80].strip("._-") or "file"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(target_dir) / ("%s_%s" % (stamp, safe))
    n = 1
    while path.exists():
        path = Path(target_dir) / ("%s_%s_%s" % (stamp, n, safe))
        n += 1
    path.write_bytes(data)
    return path
