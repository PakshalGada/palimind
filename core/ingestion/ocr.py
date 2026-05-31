import easyocr
import numpy as np
from PIL import Image
import io

# Singleton reader to avoid reloading models
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        # gpu=True will use CUDA if available, fallback to CPU
        _reader = easyocr.Reader(['en'], gpu=True)
    return _reader

def extract_text_from_image(image_bytes: bytes) -> str:
    """
    Given image bytes, run easyocr and return extracted text.
    """
    try:
        reader = get_reader()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # Convert PIL to numpy for easyocr
        img_np = np.array(image)
        results = reader.readtext(img_np, detail=0, paragraph=True)
        return "\n".join(results)
    except Exception as e:
        print(f"OCR Error: {e}")
        return ""
