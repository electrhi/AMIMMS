#!/usr/bin/env bash
echo "🔧 Installing dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
echo "✅ Build completed."
