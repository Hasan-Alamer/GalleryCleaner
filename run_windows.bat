@echo off
REM GalleryCleaner launcher — Windows.
REM First run: checks whether the libraries are installed and downloads them
REM if needed. After that it starts the app directly.
setlocal
cd /d "%~dp0"

set PY=venv\Scripts\python.exe

if exist "%PY%" (
    "%PY%" -c "import torch, torchvision, open_clip, cv2, PIL, imagehash, numpy, pillow_heif; from rapidocr import RapidOCR" >nul 2>nul
    if not errorlevel 1 goto run
)

echo ==^> First run: libraries missing - installing now (one time only)...

echo ==^> Checking Python...
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from https://python.org
    echo        and check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)
python -c "import sys; assert sys.version_info >= (3, 10)" 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.10 or newer is required.
    pause
    exit /b 1
)
python -c "import tkinter" 2>nul
if errorlevel 1 (
    echo ERROR: tkinter is missing. Re-run the Python installer and enable
    echo        "tcl/tk and IDLE" under Optional Features.
    pause
    exit /b 1
)

echo ==^> Creating virtualenv .\venv ...
if not exist venv python -m venv venv

echo ==^> Installing base dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet
venv\Scripts\pip install --quiet pillow pillow-heif imagehash numpy opencv-python-headless
if errorlevel 1 goto fail

echo ==^> Installing PyTorch (CPU wheels - both packages MUST come from the
echo     CPU index; PyPI torchvision is incompatible with CPU-index torch)...
venv\Scripts\pip install --quiet torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto fail

echo ==^> Installing OpenCLIP...
venv\Scripts\pip install --quiet open_clip_torch
if errorlevel 1 goto fail

echo ==^> Installing RapidOCR (English + Arabic OCR, ONNX runtime)...
venv\Scripts\pip install --quiet rapidocr onnxruntime python-bidi
if errorlevel 1 goto fail

echo ==^> Verifying installation...
"%PY%" -c "import torch, torchvision, open_clip, cv2, PIL, imagehash, numpy, pillow_heif; from rapidocr import RapidOCR; print('  torch', torch.__version__, '- all imports OK')"
if errorlevel 1 goto fail

echo.
echo Setup complete. The CLIP model (~600MB) and OCR models download
echo automatically on the first scan and are cached - fully offline after that.
echo.

:run
echo ==^> Starting GalleryCleaner...
"%PY%" app.py
endlocal
exit /b 0

:fail
echo ERROR: installation failed.
pause
exit /b 1
