#!/usr/bin/env bash
# GalleryCleaner launcher — macOS (double-clickable .command file).
# First run: checks whether the libraries are installed and downloads them
# if needed (via setup.sh). After that it starts the app directly.
set -euo pipefail
cd "$(dirname "$0")"

PY=./venv/bin/python

check_deps() {
    [ -x "$PY" ] && "$PY" - <<'EOF' >/dev/null 2>&1
import torch, torchvision, open_clip, cv2, PIL, imagehash, numpy, pillow_heif
from rapidocr import RapidOCR
EOF
}

if check_deps; then
    echo "==> Libraries OK."
else
    echo "==> First run: libraries missing — installing now (one time only)..."
    bash setup.sh
    check_deps || { echo "ERROR: setup finished but libraries still missing."; read -r -p "Press Enter to close..."; exit 1; }
fi

echo "==> Starting GalleryCleaner..."
exec "$PY" app.py
