"""
OCR Service for Palivision.

Uses EasyOCR to extract text from screenshots.
The EasyOCR Reader is loaded once and cached — first call is slow (~5s),
all subsequent calls are fast.

Install dependency if not already done:
    pip install easyocr
"""

import io
import base64
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_reader():
    """
    Loads the EasyOCR reader. This is cached so it only loads once.
    gpu=False means it runs on CPU — works on all machines.
    ['en'] means it reads English text.
    """
    import easyocr  # imported here so the module loads only when first needed
    logger.info("[Palivision OCR] Loading EasyOCR model (first-time load, may take ~5s)...")
    reader = easyocr.Reader(['en'], gpu=False)
    logger.info("[Palivision OCR] EasyOCR model loaded successfully.")
    return reader


def extract_text_from_b64(image_b64: str) -> str:
    """
    Takes a base64-encoded PNG image string (no data URL prefix).
    Returns all text found in the image as a single string, one paragraph per line.
    Returns an empty string if no text is found or if EasyOCR is not installed.

    Args:
        image_b64: Base64-encoded PNG bytes (the raw base64, not a data URL)

    Returns:
        Extracted text as a string, or "" if nothing found.
    """
    try:
        image_bytes = base64.b64decode(image_b64)
        reader = _get_reader()
        # detail=0 returns just the text strings (not bounding boxes)
        # paragraph=True groups nearby words into paragraphs
        results = reader.readtext(image_bytes, detail=0, paragraph=True)
        extracted = "\n".join(str(r) for r in results if r)
        logger.info(f"[Palivision OCR] Extracted {len(extracted)} characters of text.")
        return extracted
    except ImportError:
        logger.warning("[Palivision OCR] EasyOCR not installed. Run: pip install easyocr")
        return ""
    except Exception as e:
        logger.error(f"[Palivision OCR] Error during text extraction: {e}")
        return ""
