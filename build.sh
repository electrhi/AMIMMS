#!/usr/bin/env bash
echo "🔧 Installing dependencies..."

pip install --upgrade pip setuptools wheel

# Pillow 문제 해결 (버전 강제)
pip install Pillow==10.2.0

# Flask, gunicorn, 기타 패키지 재설치
pip install Flask==3.0.3 gunicorn==22.0.0 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2

echo "✅ Build completed."
