#!/usr/bin/env bash
pip install --upgrade pip setuptools wheel
pip install Pillow==10.2.0


echo "🔧 Installing dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
echo "✅ Build completed."
