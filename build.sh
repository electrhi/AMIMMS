#!/usr/bin/env bash
echo "🔧 Installing dependencies..."

pip install --upgrade pip setuptools wheel

# Pillow 최신 안정 버전 강제 재설치
pip install --force-reinstall Pillow==10.2.0

# 주요 패키지 재설치
pip install Flask==3.0.3 gunicorn==22.0.0 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2

echo "✅ Build completed."

# 👇 Pillow 모듈 확인용 (자동 디버깅)
python -c "import PIL; print('✅ Pillow installed at', PIL.__path__)"
