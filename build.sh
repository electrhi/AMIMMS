#!/usr/bin/env bash
# Render용 Python 버전 강제 빌드 스크립트

echo "📦 Using Python 3.11 runtime..."
echo "python-3.11.9" > runtime.txt

pip install --upgrade pip
pip install -r requirements.txt
