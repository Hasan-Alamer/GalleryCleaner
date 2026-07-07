#!/usr/bin/env bash
# GalleryCleaner — one-shot setup script for Linux and macOS.
# Creates a virtualenv and installs all dependencies (CPU-only, fully local).
# Windows users: run_windows.bat installs everything itself.
set -euo pipefail

cd "$(dirname "$0")"

OS="$(uname -s)"
echo "==> Detected OS: $OS"

echo "==> Checking Python..."
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
"$PYTHON" -c 'import tkinter' 2>/dev/null || {
    echo "ERROR: tkinter is missing. Install it first:"
    echo "  Fedora:        sudo dnf install python3-tkinter"
    echo "  Debian/Ubuntu: sudo apt install python3-tk"
    echo "  macOS (brew):  brew install python-tk"
    exit 1
}

echo "==> Creating virtualenv ./venv ..."
[ -d venv ] || "$PYTHON" -m venv venv

echo "==> Installing base dependencies..."
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install --quiet pillow pillow-heif imagehash numpy opencv-python-headless

echo "==> Installing PyTorch (CPU)..."
if [ "$OS" = "Darwin" ]; then
    # macOS wheels on PyPI are already CPU/Metal builds
    ./venv/bin/pip install --quiet torch torchvision
else
    # Linux: BOTH must come from the CPU index — PyPI torchvision is
    # incompatible with CPU-index torch
    ./venv/bin/pip install --quiet torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

echo "==> Installing OpenCLIP..."
./venv/bin/pip install --quiet open_clip_torch

echo "==> Installing RapidOCR (English + Arabic OCR, ONNX runtime)..."
./venv/bin/pip install --quiet rapidocr onnxruntime python-bidi

echo "==> Verifying installation..."
./venv/bin/python - <<'EOF'
import torch, torchvision, open_clip, cv2, PIL, imagehash, numpy, pillow_heif
from rapidocr import RapidOCR
print(f"  torch {torch.__version__} | opencv {cv2.__version__} | all imports OK")
EOF

echo
echo "Setup complete. Notes:"
echo "  * The CLIP model (~600MB) and OCR models download automatically on the"
echo "    first scan and are cached in ~/.cache — subsequent runs are offline."
echo
echo "Run the app with:"
echo "  ./venv/bin/python app.py"
