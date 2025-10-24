#!/usr/bin/env bash
# Render 전용 빌드 스크립트

echo "🔧 Setting up Render build environment..."

# pip 최신화
pip install --upgrade pip setuptools wheel

# 필수 패키지 직접 설치 (Render PATH 이슈 방지)
pip install Flask==3.0.3 gunicorn==22.0.0 Pillow==10.0.1 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2

echo "✅ All dependencies installed successfully."
