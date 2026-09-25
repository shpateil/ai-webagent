"""картинки для моделей: всегда сжимаем и следим, чтобы размер не ломал провайдера.

проблема (нашли 2026-09-13): модели вроде glm-5.3-flash считают картинку по сырым
байтам, поэтому png на 3.9 мб превращался в ~8000 image-токенов и провайдер отвечал
503 capacity_unavailable. у владельца проходило, у кентов нет.
решение: любую картинку гоним через pillow в jpeg 1600px, и если модель всё равно
упала — отвечаем по описанию от vision-модели, а не молчим.
"""
import base64
import io

log = __import__("logging").getLogger("vision")

MAX_EDGE = 1600      # длинная сторона после сжатия
JPEG_Q = 80          # качество jpeg


def shrink(data: bytes, mime: str = "image/jpeg", max_edge: int = MAX_EDGE):
    """картинка -> (data_url, байт после сжатия). не смогли — отдаём как есть."""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        scale = min(1.0, max_edge / max(w, h))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
        small = buf.getvalue()
        # если сжатие не помогло (картинка и была мелкой/нежней) — шлём как есть
        if len(small) >= len(data):
            small = data
            return "data:" + (mime or "image/jpeg") + ";base64," + base64.b64encode(data).decode(), len(data)
        return "data:image/jpeg;base64," + base64.b64encode(small).decode(), len(small)
    except Exception as e:
        log.warning("pillow не смог: %s, шлём как есть", type(e).__name__)
        return "data:" + (mime or "image/jpeg") + ";base64," + base64.b64encode(data).decode(), len(data)


def image_parts(images):
    """картинки для сообщения модели: всегда через shrink, не больше 3 штук и не больше ~1.5мб на штуку"""
    out = []
    total = 0
    for img in (images or [])[:3]:
        try:
            data = img.get("data") if isinstance(img, dict) else img
            mime = (img.get("mime") if isinstance(img, dict) else None) or "image/jpeg"
            data_url, size = shrink(data, mime)
            if size > 2 * 1024 * 1024 and out:
                log.warning("картинка %s байт не влезла, остальные пропускаю", size)
                break
            total += size
            if total > 3 * 1024 * 1024 and out:
                break
            out.append({"type": "image_url", "image_url": {"url": data_url}})
        except Exception as e:
            log.warning("картинка не собралась: %s", e)
    return out
