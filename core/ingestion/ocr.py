import io

import numpy as np
from PIL import Image

from core.exceptions import OCRError

_reader = None


def get_reader(gpu: bool = True):
    global _reader
    if _reader is None:
        import easyocr  # lazy import — only load when OCR is actually needed
        _reader = easyocr.Reader(["en"], gpu=gpu)
    return _reader


def extract_text_from_image(image_bytes: bytes) -> str:
    """Given image bytes, run easyocr and return extracted text."""
    try:
        reader = get_reader(gpu=True)
        return _run_readtext(reader, image_bytes)
    except Exception as gpu_err:
        # GPU unavailable / out of memory → retry on CPU
        try:
            import easyocr
            reader = easyocr.Reader(["en"], gpu=False)
            return _run_readtext(reader, image_bytes)
        except Exception as cpu_err:
            raise OCRError(f"OCR failed (gpu: {gpu_err}; cpu: {cpu_err})") from cpu_err


def _run_readtext(reader, image_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_np = np.array(image)
    results = reader.readtext(img_np, detail=0, paragraph=True)
    return "\n".join(results)
