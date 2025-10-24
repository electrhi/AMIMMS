#!/usr/bin/env bash
# Render Python 환경 강제 세팅 및 패키지 설치

echo "🔧 Installing dependencies manually..."
pip install --upgrade pip setuptools wheel

pip install Flask==3.0.3 gunicorn==21.2.0 Pillow==10.0.1 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2

echo "✅ All dependencies installed successfully."
