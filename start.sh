#!/usr/bin/env bash
echo "🚀 Starting Gunicorn..."

# Render 환경에서 가상환경 경로를 명시적으로 추가
export PATH="/opt/render/project/src/.venv/bin:$PATH"

# gunicorn 실행
exec /opt/render/project/src/.venv/bin/gunicorn --workers=2 --bind 0.0.0.0:$PORT app:app
