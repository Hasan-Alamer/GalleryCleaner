# -*- coding: utf-8 -*-
"""File operations: recoverable .trash bin, atomic writes, hashes, CSV report."""

import csv
import hashlib
import json
import os
import shutil
from datetime import datetime

import config


def _trash_dir(base_folder: str) -> str:
    return os.path.join(base_folder, config.TRASH_DIR_NAME)


def _metadata_path(base_folder: str) -> str:
    return os.path.join(_trash_dir(base_folder), config.TRASH_METADATA)


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_metadata(base_folder: str) -> list:
    p = _metadata_path(base_folder)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # corrupt file: don't delete it — keep a copy for manual inspection
            shutil.copy2(p, p + ".corrupt")
            return []
    return []


def _save_metadata_atomic(base_folder: str, entries: list):
    """Atomic write: temp file then rename — no corruption on abrupt shutdown."""
    p = _metadata_path(base_folder)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _unique_name(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate, i = filename, 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{i}{ext}"
        i += 1
    return candidate


def move_to_trash(base_folder: str, paths: list) -> int:
    """Move files into .trash, recording their hash. Returns count moved."""
    trash = _trash_dir(base_folder)
    os.makedirs(trash, exist_ok=True)
    entries = _load_metadata(base_folder)
    moved = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        fh = file_hash(path)
        trash_name = _unique_name(trash, os.path.basename(path))
        shutil.move(path, os.path.join(trash, trash_name))
        entries.append({
            "filename": trash_name,
            "original_path": os.path.abspath(path),
            "deleted_at": datetime.now().isoformat(timespec="seconds"),
            "file_hash": fh,
        })
        moved += 1
    _save_metadata_atomic(base_folder, entries)
    return moved


def list_trash(base_folder: str) -> list:
    return _load_metadata(base_folder)


def restore_from_trash(base_folder: str, filenames: list = None) -> int:
    """Restore files (all when None) after verifying hashes. Returns count."""
    entries = _load_metadata(base_folder)
    trash = _trash_dir(base_folder)
    remaining, restored = [], 0
    for e in entries:
        if filenames is not None and e["filename"] not in filenames:
            remaining.append(e)
            continue
        src = os.path.join(trash, e["filename"])
        if not os.path.isfile(src) or file_hash(src) != e["file_hash"]:
            # hash mismatch or missing file: never restore the wrong file
            remaining.append(e)
            continue
        dest = e["original_path"]
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            dest = os.path.join(os.path.dirname(dest),
                                _unique_name(os.path.dirname(dest),
                                             os.path.basename(dest)))
        shutil.move(src, dest)
        restored += 1
    _save_metadata_atomic(base_folder, remaining)
    return restored


def empty_trash(base_folder: str) -> int:
    """Permanently delete the trash contents. Returns count deleted."""
    entries = _load_metadata(base_folder)
    trash = _trash_dir(base_folder)
    count = 0
    for e in entries:
        p = os.path.join(trash, e["filename"])
        if os.path.isfile(p):
            os.remove(p)
            count += 1
    _save_metadata_atomic(base_folder, [])
    return count


def export_csv(dest_path: str, results: list):
    """Report: file name, category, confidence, capture date, deciding stage."""
    with open(dest_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "category", "confidence", "date_taken", "stage"])
        for r in results:
            w.writerow([r.path, r.category, f"{r.confidence:.2f}",
                        r.date_taken, r.stage])
