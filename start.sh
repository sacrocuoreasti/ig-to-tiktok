#!/bin/bash
# Script per avviare il bot Instagram -> TikTok
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Configurazione ambiente virtuale..."
    /usr/bin/python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    playwright install chromium
else
    source .venv/bin/activate
fi

echo "Avvio della dashboard web su http://localhost:5005 ..."
python3 app.py

