# GalleryCleaner

**A smart, 100% offline gallery cleaner.** GalleryCleaner scans a photo folder, understands what each image actually *is* — receipts, screenshots, memes, blurry shots, duplicates, study notes — and lets you sweep the junk into a recoverable trash with one click.

No internet. No servers. No accounts. Every model runs locally on your CPU.

---

## Features

- **AI classification into 15+ categories** — study material, receipts, screenshots, chat screenshots, memes, QR codes, business cards, handwritten notes, book pages, food, animals, landscapes, people, text documents, and more (CLIP vision-language model with multi-prompt averaging)
- **Confidence threshold** — anything below 65% confidence lands in *unclassified* for manual review instead of being mislabeled
- **Multi-stage pipeline, cheapest first** — EXIF metadata settles screenshots for free, OpenCV catches blurry/dark shots in milliseconds, and only the survivors reach the neural network
- **Three-level duplicate detection** — exact copies, near-duplicates (resized/recompressed), and *semantic* duplicates (burst shots of the same scene) shown as groups
- **Bilingual OCR (English + Arabic)** — reads text inside document-like images; a keyword like "invoice" or "فاتورة" definitively re-classifies an image as a receipt, and sensitive content gets flagged
- **Safe deletion always** — files move to a `.trash/` folder with SHA-256 hashes and atomic metadata writes; restore everything with one click; nothing is permanently deleted without an explicit, loud confirmation
- **A UI that never freezes** — all computation runs on a background thread; live progress bar with ETA, per-category counters, paginated thumbnail grid, red→green confidence bar under every thumbnail
- **CSV report export** — file, category, confidence, capture date, deciding stage

## Platform support

| Platform | Status | Run |
|---|---|---|
| **Linux** | ✅ Supported | `./run_linux.sh` |
| **Windows 10/11** | ✅ Supported | double-click `run_windows.bat` |
| **macOS** | ✅ Supported | double-click `run_macos.command` |
| iOS / Android | ❌ Not possible | This is a Python desktop app (Tkinter + PyTorch); mobile OSes cannot run it. A mobile version would be a separate project. |

## Quick start

**Requirements:** Python 3.10+ with tkinter, ~3 GB disk (dependencies + models), 8 GB RAM recommended.

Just run the launcher for your platform — **on first run it checks whether the
libraries are installed and downloads them automatically if not**, then starts
the app. Every run after that starts instantly.

```bash
# Linux
./run_linux.sh

# macOS (or double-click run_macos.command in Finder)
./run_macos.command

# Windows (or double-click run_windows.bat in Explorer)
run_windows.bat
```

If tkinter is missing: `sudo dnf install python3-tkinter` (Fedora), `sudo apt install python3-tk` (Debian/Ubuntu), `brew install python-tk` (macOS). On Windows, re-run the Python installer and enable **tcl/tk and IDLE**.

To install dependencies manually without launching, run `setup.sh` (Linux/macOS). On Windows the launcher itself handles installation.

> **First run:** the CLIP model (~600 MB) and OCR models download once and are cached. After that, everything works fully offline.

## Usage

1. **Choose Folder…** — pick the folder to clean (subfolders are scanned too; hidden folders are skipped)
2. **Start Scan** — watch live progress, ETA, and category counts
3. Click a **category** in the sidebar to browse its thumbnails
4. Click thumbnails to **select** (cyan border + ✓ badge), or use **Select all** / **Select < 70% confidence**
5. **Remove Selected** or **Remove ALL in category** — files go to `.trash/`, fully recoverable
6. **Restore all from trash** to undo, or **Empty trash permanently** when you're sure

**Keyboard:** `Ctrl+A` select all · `Delete` remove selected · `Escape` clear selection · `PgUp`/`PgDn` pages · double-click for full-size preview

## How it works

```
image ──► Stage 0  EXIF metadata     (free — screenshots settled deterministically)
     ──► Stage 1  OpenCV filters     (ms — blurry / dark caught before any AI)
     ──► Stage 2  Perceptual hashes  (exact + near duplicate fingerprints)
     ──► Stage 3  CLIP (open_clip)   (one embedding, used 3×: classify with
                                      multi-prompt averaging + 0.65 threshold,
                                      semantic dedup, future aesthetic score)
     ──► Stage 4  RapidOCR EN+AR     (conditional — document-like images only;
                                      keywords confirm receipts / flag sensitive)
```

| File | Role |
|---|---|
| `config.py` | All tunables: model profiles, category prompts, thresholds, formats |
| `classifier.py` | The pipeline, CLIP engine, duplicate clustering |
| `ocr.py` | Dual English + Arabic OCR (RapidOCR over ONNX) |
| `file_ops.py` | Trash with hash verification + atomic writes, CSV export |
| `app.py` | Tkinter UI — light theme, background worker, action bar |

## Configuration

Edit `config.py`:

- `CATEGORY_PROMPTS` — add/remove categories or tune their prompt sentences
- `CONFIDENCE_THRESHOLD` (0.65) — raise for fewer false positives
- `BLUR_THRESHOLD`, `DARK_THRESHOLD`, `HAMMING_THRESHOLD`, `COSINE_DUP_THRESHOLD`
- `OCR_KEYWORDS` — bilingual keyword lists that trigger definitive classification
- `SUPPORTED_FORMATS` — jpg, png, webp, bmp, tiff, **HEIC/HEIF** (iPhone photos)

## Roadmap

- **Phase 2** — MobileCLIP-S2 (fast) / SigLIP (accurate) profiles, ONNX Runtime inference
- **Phase 3** — face detection (selfies/groups/closed eyes via MediaPipe), aesthetic scoring with "best of group" badges
- **Phase 4** — hover previews, date/source filters, lazy thumbnail loading
- **Phase 5** — adaptive learning from your corrections

## Privacy

GalleryCleaner never opens a network connection except the one-time model download at setup. Your photos never leave your machine.
