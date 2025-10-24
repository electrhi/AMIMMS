#!/usr/bin/env bash
echo "🚀 Starting Gunicorn..."

# 자동으로 gunicorn 위치 탐색
GUNICORN_PATH=$(find /opt/render/project/src -type f -name gunicorn | head -n 1)

if [ -z "$GUNICORN_PATH" ]; then
  echo "❌ gunicorn not found, installing..."
  pip install gunicorn
  GUNICORN_PATH=$(find /opt/render/project/src -type f -name gunicorn | head -n 1)
fi

echo "✅ Using gunicorn from: $GUNICORN_PATH"
exec $GUNICORN_PATH --workers=2 --bind 0.0.0.0:$PORT app:app
