#!/usr/bin/env bash
# Render Python 환경 강제 고정 빌드 스크립트

echo "🔧 Setting up Python 3.11 environment..."
echo "python-3.11.9" > runtime.txt

# pip 최신화
pip install --upgrade pip setuptools wheel

# 패키지 설치
pip install Flask==3.0.3 gunicorn==21.2.0 Pillow==9.5.0 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2

echo "✅ All dependencies installed successfully."
