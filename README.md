# web agent

личный веб-агент на fastapi с авторизацией, чатами, файлами, инструментами и стримингом ответа.

## запуск

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8091
```

## настройки

секреты лежат в `.env` и не добавляются в репозиторий:

```text
AI_LOGIN=
AI_PASSWORD=
AI_COOKIE_SECRET=
CVC_API_KEY=
CLINE_API_KEY=
OPENROUTER_API_KEY=
```

пути к данным, базе, рабочей папке и провайдерам переопределяются переменными из `config.py`.

## проверка

```bash
node --check static/app.js
node --check static/theme.js
python3 -m compileall -q app.py memory.py agent.py tools.py config.py vision.py
```

живой сервис работает за nginx на `your-domain.example`. база, загрузки, вложения и рабочие файлы находятся вне репозитория.
