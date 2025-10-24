#!/usr/bin/env bash
echo "🚀 Starting Gunicorn..."
export PATH="$PATH:/opt/render/project/src/.venv/bin"
exec gunicorn --workers=2 --bind 0.0.0.0:$PORT app:app
