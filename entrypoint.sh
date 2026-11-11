#!/bin/sh
set -e

# Default to 10000 if PORT is not set or empty (Render default)
PORT="${PORT:-10000}"

echo "================================================="
echo "[*] Avvio ReelSync (Instagram -> TikTok via Zernio)"
echo "[*] In ascolto su: 0.0.0.0:${PORT}"
echo "================================================="

# Start Gunicorn production WSGI server
exec python3 -m gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    app:app
