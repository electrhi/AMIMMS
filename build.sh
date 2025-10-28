#!/usr/bin/env bash
echo "🔧 Installing dependencies..."

pip install --upgrade pip setuptools wheel

# Pillow 최신버전으로 변경 (10.3.0 이상)
pip install --force-reinstall Pillow==11.0.0

# 나머지 주요 패키지
pip install Flask==3.0.3 gunicorn==22.0.0 qrcode==7.4.2 openpyxl==3.1.2 pandas==2.2.3 google-auth==2.35.0 gspread==6.1.2 google-api-python-client==2.147.0 google-cloud-storage==2.18.2 google-auth-httplib2==0.2.0 requests==2.32.3 protobuf==6.33.0 certifi==2025.10.5 urllib3==2.2.3


echo "✅ Build completed."

# Pillow 경로 디버깅용
python -c "import PIL; print('✅ Pillow installed at', PIL.__path__)"
