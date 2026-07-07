# -*- coding: utf-8 -*-
"""Multi-stage classification pipeline — cheapest computation first.

Stages:
  0) EXIF/metadata read            (nearly free — settles screenshots deterministically)
  1) fast OpenCV filters           (blur/darkness)
  2) perceptual hashing imagehash  (exact + near duplicates)
  3) CLIP via open_clip            (semantic classification with a confidence
                                    threshold + embeddings)
  4) RapidOCR (English + Arabic)   (conditional — only for document-like
                                    categories; confirms receipts, flags
                                    sensitive content, counts text density)

The app degrades gracefully: if torch/open_clip are missing, stages 0-2
still run and the remaining images are tagged "unclassified".
"""

import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ExifTags
import imagehash

import config
import ocr

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    import cv2
except ImportError:
    cv2 = None

_CAMERA_EXIF_TAGS = {"Make", "Model", "ExposureTime", "FocalLength", "FNumber"}


@dataclass
class ImageResult:
    path: str
    category: str = config.UNCLASSIFIED_LABEL
    confidence: float = 0.0
    stage: str = ""           # pipeline stage that settled the classification
    date_taken: str = ""
    from_camera: bool = False
    embedding: object = None  # np.ndarray — reused later for semantic dedup
    extras: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 0: EXIF
# ---------------------------------------------------------------------------
def read_exif_heuristics(img: Image.Image) -> dict:
    """Return {is_screenshot, from_camera, date_taken} from metadata only."""
    info = {"is_screenshot": False, "from_camera": False, "date_taken": ""}
    try:
        exif = img.getexif()
    except Exception:
        return info
    if not exif:
        # a PNG with no EXIF at all is the classic screenshot candidate
        if (img.format or "").upper() == "PNG":
            info["is_screenshot"] = True
        return info

    named = {}
    for tag_id, value in exif.items():
        named[ExifTags.TAGS.get(tag_id, tag_id)] = value

    has_camera_fields = bool(_CAMERA_EXIF_TAGS & set(named))
    info["from_camera"] = has_camera_fields
    software = str(named.get("Software", "")).lower()
    if not has_camera_fields and ("screenshot" in software or not named.get("Model")):
        # no camera fields: screenshot or saved-from-internet — call it a
        # screenshot only when the format is PNG or the capture app is named
        if "screenshot" in software or (img.format or "").upper() == "PNG":
            info["is_screenshot"] = True
    date = named.get("DateTimeOriginal") or named.get("DateTime") or ""
    info["date_taken"] = str(date)
    return info


# ---------------------------------------------------------------------------
# Stage 1: OpenCV filters
# ---------------------------------------------------------------------------
def quality_check(img: Image.Image) -> str | None:
    """Return "blurry", "dark" or None. Runs on a downscaled copy for speed."""
    if cv2 is None:
        return None
    small = img.convert("L").copy()
    small.thumbnail((512, 512))
    arr = np.asarray(small)
    if arr.mean() < config.DARK_THRESHOLD:
        return "dark"
    if cv2.Laplacian(arr, cv2.CV_64F).var() < config.BLUR_THRESHOLD:
        return "blurry"
    return None


# ---------------------------------------------------------------------------
# Stage 3: CLIP (lazy-loaded, once)
# ---------------------------------------------------------------------------
class ClipEngine:
    def __init__(self):
        self._lock = threading.Lock()
        self._loaded = False
        self.available = False
        self.model = None
        self.preprocess = None
        self.tokenizer = None
        self.category_names = []
        self.text_features = None  # text fingerprints (mean of each category's prompts)

    def _load(self):
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                import torch
                import open_clip
            except ImportError:
                return
            profile = config.MODEL_PROFILES[config.ACTIVE_PROFILE]
            try:
                model, _, preprocess = open_clip.create_model_and_transforms(
                    profile["name"], pretrained=profile["pretrained"])
                tokenizer = open_clip.get_tokenizer(profile["name"])
            except Exception:
                return
            model.eval()
            self.model, self.preprocess, self.tokenizer = model, preprocess, tokenizer
            self._torch = torch
            # text fingerprint per category = mean of all its prompt embeddings
            feats = []
            with torch.no_grad():
                for cat, prompts in config.CATEGORY_PROMPTS.items():
                    tokens = tokenizer(prompts)
                    tf = model.encode_text(tokens)
                    tf = tf / tf.norm(dim=-1, keepdim=True)
                    feats.append(tf.mean(dim=0))
                    self.category_names.append(cat)
            tfm = torch.stack(feats)
            self.text_features = tfm / tfm.norm(dim=-1, keepdim=True)
            self.available = True

    def classify(self, img: Image.Image):
        """Return (category, confidence, embedding) or None if no model."""
        self._load()
        if not self.available:
            return None
        torch = self._torch
        with torch.no_grad():
            tensor = self.preprocess(img.convert("RGB")).unsqueeze(0)
            feat = self.model.encode_image(tensor)
            feat = feat / feat.norm(dim=-1, keepdim=True)
            probs = (100.0 * feat @ self.text_features.T).softmax(dim=-1)[0]
            conf, idx = probs.max(dim=0)
        conf = float(conf)
        embedding = feat[0].cpu().numpy()
        if conf >= config.CONFIDENCE_THRESHOLD:
            return self.category_names[int(idx)], conf, embedding
        return config.UNCLASSIFIED_LABEL, conf, embedding


_engine = ClipEngine()


def clip_available() -> bool:
    _engine._load()
    return _engine.available


# ---------------------------------------------------------------------------
# Folder scanning
# ---------------------------------------------------------------------------
def iter_image_paths(folder: str):
    if config.RECURSIVE_SCAN:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs
                       if not d.startswith(config.EXCLUDED_DIR_PREFIXES)]
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in config.SUPPORTED_FORMATS:
                    yield os.path.join(root, f)
    else:
        for f in sorted(os.listdir(folder)):
            p = os.path.join(folder, f)
            if os.path.isfile(p) and \
                    os.path.splitext(f)[1].lower() in config.SUPPORTED_FORMATS:
                yield p


def classify_folder(folder: str, stop_event: threading.Event = None):
    """Generator: run each image through the pipeline, yield ImageResult.

    Duplicate detection runs after the scan completes via find_similar_groups().
    """
    for path in iter_image_paths(folder):
        if stop_event is not None and stop_event.is_set():
            return
        result = ImageResult(path=path)
        try:
            with Image.open(path) as img:
                img.load()
                # Stage 0: metadata
                exif = read_exif_heuristics(img)
                result.date_taken = exif["date_taken"]
                result.from_camera = exif["from_camera"]
                if exif["is_screenshot"]:
                    result.category, result.confidence = "screenshots", 1.0
                    result.stage = "metadata"
                    # pass through CLIP for sub-categorization when available
                    sub = _engine.classify(img) if clip_available() else None
                    if sub and sub[0] == "chat_screenshots":
                        result.category = "chat_screenshots"
                        result.confidence = sub[1]
                    if sub:
                        result.embedding = sub[2]
                    result.extras["hash"] = _hashes(img)
                    yield result
                    continue
                # Stage 1: quality
                quality = quality_check(img)
                if quality:
                    result.category, result.confidence = quality, 1.0
                    result.stage = "opencv"
                    result.extras["hash"] = _hashes(img)
                    yield result
                    continue
                # Stage 2: duplicate fingerprints (always collected)
                result.extras["hash"] = _hashes(img)
                # Stage 3: CLIP
                clip_out = _engine.classify(img)
                if clip_out:
                    result.category, result.confidence, result.embedding = clip_out
                    result.stage = "clip"
                # Stage 4 (conditional): OCR — document-like categories only
                if (result.category in config.OCR_TRIGGER_CATEGORIES
                        or result.category == config.UNCLASSIFIED_LABEL) \
                        and ocr.available():
                    info = ocr.analyze(img)
                    result.extras["text"] = info["text"]
                    result.extras["ocr_tags"] = info["keywords"]
                    if "receipts" in info["keywords"]:
                        # keyword hit is definitive — overrides CLIP doubt
                        result.category, result.confidence = "receipts", 1.0
                        result.stage = "ocr"
                    elif info["char_count"] >= config.OCR_MIN_CHARS \
                            and result.category == config.UNCLASSIFIED_LABEL:
                        result.category = "text_document"
                        result.confidence = 0.9
                        result.stage = "ocr"
        except Exception as exc:
            result.category = "corrupted"
            result.stage = "error"
            result.extras["error"] = str(exc)
        yield result


def _hashes(img: Image.Image) -> dict:
    rgb = img.convert("RGB")
    gray = np.asarray(rgb.convert("L").resize((32, 32)))
    return {"ahash": imagehash.average_hash(rgb),
            "dhash": imagehash.dhash(rgb),
            "mean": float(gray.mean())}


# ---------------------------------------------------------------------------
# Three-level duplicate detection — returns clusters
# ---------------------------------------------------------------------------
def find_similar_groups(results: list) -> list:
    """Return a list of groups; each group is a dict with paths and level.

    Level 1: exact hash match. Level 2: Hamming distance <= HAMMING_THRESHOLD.
    Level 3: cosine similarity >= COSINE_DUP_THRESHOLD on embeddings.
    """
    items = [r for r in results if r.extras.get("hash")]
    n = len(items)
    parent = list(range(n))
    level = {}  # merged root idx → lowest level that captured the link

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, lv):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        root = find(ra)
        level[root] = min(level.get(root, lv), lv)

    # Levels 1 and 2 via dhash — with a brightness guard: flat images
    # (all-black/all-white) produce a spuriously identical all-zero dhash
    for i in range(n):
        hi = items[i].extras["hash"]
        for j in range(i + 1, n):
            hj = items[j].extras["hash"]
            if abs(hi["mean"] - hj["mean"]) > 25:
                continue
            dist = hi["dhash"] - hj["dhash"]
            if dist == 0 and hi["ahash"] - hj["ahash"] == 0:
                union(i, j, 1)
            elif dist <= config.HAMMING_THRESHOLD:
                union(i, j, 2)

    # Level 3: semantic — near-zero extra cost on already-computed vectors
    embs = [(k, r.embedding) for k, r in enumerate(items)
            if r.embedding is not None]
    if len(embs) > 1:
        idxs, vecs = zip(*embs)
        mat = np.stack(vecs)
        sims = mat @ mat.T
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                if sims[a, b] >= config.COSINE_DUP_THRESHOLD:
                    union(idxs[a], idxs[b], 3)

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    out = []
    for root, members in groups.items():
        if len(members) > 1:
            out.append({
                "paths": [items[m].path for m in members],
                "level": level.get(root, 3),
            })
    return out
