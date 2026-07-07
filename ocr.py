# -*- coding: utf-8 -*-
"""OCR stage — RapidOCR (ONNX) with dual English + Arabic recognition.

Two recognition engines share one detector family; both run on the image
and their texts are merged, so mixed Arabic/English documents (receipts,
study notes, chat screenshots) are read completely.

Lazy-loaded: the models download on first use and the app degrades
gracefully if rapidocr is not installed.
"""

import threading

import numpy as np

import config

_lock = threading.Lock()
_engines = None  # None = not tried yet, [] = unavailable


def _load():
    global _engines
    with _lock:
        if _engines is not None:
            return
        try:
            from rapidocr import RapidOCR, LangRec, OCRVersion, ModelType
            engines = []
            if "en" in config.OCR_LANGS:
                engines.append(RapidOCR())  # default model reads Latin/English
            if "arabic" in config.OCR_LANGS:
                # Arabic recognition is only available in PP-OCRv4 mobile
                engines.append(RapidOCR(params={
                    "Rec.lang_type": LangRec.ARABIC,
                    "Rec.ocr_version": OCRVersion.PPOCRV4,
                    "Rec.model_type": ModelType.MOBILE,
                }))
            _engines = engines
        except Exception:
            _engines = []


def available() -> bool:
    _load()
    return bool(_engines)


def extract_text(img) -> str:
    """Run every language engine on a PIL image and merge unique lines."""
    _load()
    if not _engines:
        return ""
    arr = np.asarray(img.convert("RGB"))
    lines = []
    seen = set()
    for engine in _engines:
        try:
            result = engine(arr)
        except Exception:
            continue
        for txt in (result.txts or []):
            txt = txt.strip()
            if txt and txt not in seen:
                seen.add(txt)
                lines.append(txt)
    return "\n".join(lines)


def analyze(img) -> dict:
    """Return {text, char_count, keywords: [tags]} for one image."""
    text = extract_text(img)
    # Arabic lines come back in display (visual) order, i.e. reversed
    # relative to logical order — match keywords against both directions.
    lines = text.lower().splitlines()
    corpus = lines + [ln[::-1] for ln in lines]
    tags = [tag for tag, words in config.OCR_KEYWORDS.items()
            if any(w.lower() in ln for w in words for ln in corpus)]
    return {"text": text, "char_count": len(text), "keywords": tags}
