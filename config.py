# -*- coding: utf-8 -*-
"""Gallery Cleaner — central configuration."""

# ---------------------------------------------------------------------------
# Model profile system — Phase 2 of the roadmap enables MobileCLIP/SigLIP.
# For now the default is ViT-B-32 since it is available through open_clip
# with no extra dependencies.
# ---------------------------------------------------------------------------
MODEL_PROFILES = {
    "fast": {"name": "ViT-B-32", "pretrained": "laion2b_s34b_b79k"},
    "accurate": {"name": "ViT-B-16-SigLIP", "pretrained": "webli"},
}
ACTIVE_PROFILE = "fast"
USE_ONNX = False  # enabled in Phase 2 after exporting the models to ONNX

# ---------------------------------------------------------------------------
# Prompt engineering: a list of descriptive sentences per category;
# the text embeddings are averaged into one "text fingerprint" per category.
# ---------------------------------------------------------------------------
CATEGORY_PROMPTS = {
    "study_material": [
        "a photo of a study slide or exam paper",
        "university lecture notes with diagrams",
        "a screenshot of an online course lesson",
        "a page of printed exam questions",
    ],
    "screenshots": [
        "a smartphone screenshot of an app interface",
        "a screenshot of a mobile phone screen with a status bar",
        "a computer desktop screenshot with windows and icons",
    ],
    "chat_screenshots": [
        "a whatsapp chat screenshot with message bubbles",
        "a messaging app interface with chat bubbles",
        "a telegram conversation screenshot",
    ],
    "memes": [
        "an internet meme containing humorous text overlaid on an image",
        "a funny meme image shared on social media",
        "a joke picture with bold caption text",
    ],
    "receipts": [
        "a photo of a receipt or invoice",
        "a store receipt with item prices and totals",
        "a restaurant bill printed on thermal paper",
    ],
    "qr_codes": [
        "a QR code on a white background",
        "a photo showing a large barcode or QR code",
    ],
    "whiteboards_screens": [
        "a photo of a whiteboard with writing taken in a classroom",
        "a photograph of a projector screen or TV screen taken with a phone camera",
        "a blackboard covered with handwritten equations",
    ],
    "business_cards": [
        "a clear macro photograph of a professional business card containing contact information",
        "a photo of a business card with a name, phone number and logo",
    ],
    "handwritten_notes": [
        "a close-up photo of handwritten study notes on ruled paper",
        "a notebook page filled with handwriting",
    ],
    "book_pages": [
        "a photo of an open printed book page",
        "a photograph of a page from a textbook with printed paragraphs",
    ],
    "food": [
        "food photography of a dish or meal on a plate",
        "a photo of delicious food served at a restaurant",
        "a close-up photo of a homemade meal",
    ],
    "animals": [
        "a photo of a pet dog or cat",
        "a cute animal photo",
    ],
    "landscapes": [
        "a landscape photo of nature, mountains or the sea",
        "a photo of a sunset or sunrise sky",
        "scenic outdoor photography of trees and fields",
    ],
    "people": [
        "a photo of a person or a selfie",
        "a group photo of friends posing for the camera",
        "a portrait photograph of people",
    ],
}

CONFIDENCE_THRESHOLD = 0.65  # below this → "unclassified"
UNCLASSIFIED_LABEL = "unclassified"

# ---------------------------------------------------------------------------
# Detection thresholds
# ---------------------------------------------------------------------------
BLUR_THRESHOLD = 100        # Laplacian variance
DARK_THRESHOLD = 30         # mean brightness
HAMMING_THRESHOLD = 3       # near-duplicate (dhash)
COSINE_DUP_THRESHOLD = 0.95  # semantic duplicates (Phase 2)
EAR_THRESHOLD = 0.25        # closed eyes (Phase 3)
OCR_MIN_CHARS = 100         # "document" threshold
OCR_LANGS = ["en", "arabic"]  # dual recognition: English + Arabic
# Keywords are bilingual — they must match text inside the images.
OCR_KEYWORDS = {
    "receipts": ["فاتورة", "ضريبة", "المجموع",
                 "invoice", "receipt", "total", "vat", "tax"],
    "sensitive": ["رقم الجوال", "phone number", "password", "iban"],
}
# CLIP categories that trigger the conditional OCR stage
OCR_TRIGGER_CATEGORIES = {
    "study_material", "receipts", "business_cards", "handwritten_notes",
    "book_pages", "screenshots", "chat_screenshots",
}
AESTHETIC_LOW_SCORE = 3.5

BATCH_SIZE = 16
SUPPORTED_FORMATS = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
                     ".heic", ".heif"]
RECURSIVE_SCAN = True
EXCLUDED_DIR_PREFIXES = (".",)  # hidden directories (includes .trash)

TRASH_DIR_NAME = ".trash"
TRASH_METADATA = "metadata.json"
