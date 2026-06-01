import io

import easyocr
import numpy as np
from PIL import Image

from core.exceptions import OCRError

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(["en"], gpu=True)
    return _reader


def extract_text_from_image(image_bytes: bytes) -> str:
    """Given image bytes, run easyocr and return extracted text."""
    try:
        reader = get_reader()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np = np.array(image)
        results = reader.readtext(img_np, detail=0, paragraph=True)
        return "\n".join(results)
    except Exception as e:
        raise OCRError(f"OCR failed: {e}") from e
