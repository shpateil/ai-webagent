#!/usr/bin/env bash
set -eu

cd "$(dirname "$0")"
node --check static/app.js
node --check static/theme.js
python3 -m compileall -q app.py memory.py agent.py tools.py config.py vision.py imgs.py
python3 -m unittest discover -s tests -p 'test_*.py'
printf 'checks passed\n'
