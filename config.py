import os
from pathlib import Path

BASE = Path(os.environ.get("AI_BASE", "/srv/agent"))
APP_DIR = BASE / "app"
DATA_DIR = BASE / "data"
WORK_DIR = BASE / "workspace"
SKILLS_DIR = BASE / "skills"
STATIC_DIR = APP_DIR / "static"
LOGS_DIR = BASE / "logs"


def _load_env():
    env = APP_DIR / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

CVC_KEY = os.environ.get("CVC_API_KEY", "")
CLINE_KEY = os.environ.get("CLINE_API_KEY", "")
API_URL = os.environ.get("AI_API_URL", "https://ru.cheapvibecode.ru/v1/chat/completions")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OR_URL = os.environ.get("OR_API_URL", "https://openrouter.ai/api/v1/chat/completions")
MODEL = os.environ.get("AI_MODEL", "deepseek-v4-flash")
VISION_MODEL = os.environ.get("AI_VISION_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "AI_FALLBACKS", "deepseek-v4-flash,mimo-v2.5,qwen3.8-flash").split(",") if m.strip()]

SEARCH_URL = os.environ.get("AI_SEARCH_URL", "http://127.0.0.1:8888/search")

LOGIN = os.environ.get("AI_LOGIN", "shpateil")
PASSWORD = os.environ.get("AI_PASSWORD", "")
COOKIE_SECRET = os.environ.get("AI_COOKIE_SECRET", "")
COOKIE_NAME = "ai_session"
COOKIE_DAYS = 365

HOST = "127.0.0.1"
PORT = int(os.environ.get("AI_PORT", "8091"))

PROMPT_FILE = APP_DIR / "prompt.md"
SCHOOL_FILE = APP_DIR / "school.md"
DB_FILE = DATA_DIR / "agent.db"
UPLOAD_DIR = DATA_DIR / "uploads"
NOTES_DIR = DATA_DIR / "notes"
SHARE_DIR = Path(os.environ.get("AI_SHARE_DIR", "/srv/example/files"))
SHARE_BASE = os.environ.get("AI_SHARE_BASE", "https://files.example.com/")

HISTORY_LIMIT = 40
MAX_ITER = int(os.environ.get("AI_MAX_ITER", "200"))
STEP_BURST = int(os.environ.get("AI_STEP_BURST", "6"))
BUDGET_HOURS = float(os.environ.get("AI_BUDGET_HOURS", "6"))
IMAGE_TAIL = int(os.environ.get("AI_IMAGE_TAIL", "4"))
MAX_BASH_SECONDS = 600
MAX_BASH_OUT = 8000
MAX_PROMPT_LEN = 20000
MAX_TOOL_OUT = 12000
TIMEZONE = os.environ.get("AI_TZ", "UTC")

for d in (DATA_DIR, WORK_DIR, SKILLS_DIR, LOGS_DIR, UPLOAD_DIR, NOTES_DIR, STATIC_DIR):
    d.mkdir(parents=True, exist_ok=True)