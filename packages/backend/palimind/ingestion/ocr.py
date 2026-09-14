import io

import numpy as np
from PIL import Image

from palimind.exceptions import OCRError

_reader = None


def _limit_threads() -> None:
    """Cap torch/OpenMP threads before easyocr spins up its worker pool.

    Without this, loading the easyocr (PyTorch) reader spawns a large native
    thread pool whose idle workers busy-wait a CPU core — which accumulates
    over repeated OCR calls and can wedge the API server.
    """
    import os

    for k, v in (
        ("OMP_NUM_THREADS", "2"),
        ("OMP_WAIT_POLICY", "PASSIVE"),
        ("MKL_NUM_THREADS", "2"),
    ):
        os.environ.setdefault(k, v)
    try:
        import torch

        torch.set_num_threads(2)
        torch.set_num_interop_threads(2)
    except Exception:
        pass


def get_reader(gpu: bool = True):
    global _reader
    if _reader is None:
        import easyocr  # lazy import — only load when OCR is actually needed

        _limit_threads()
        try:
            _reader = easyocr.Reader(
                ["en"],
                gpu=gpu,
                intra_op_num_threads=2,
                inter_op_num_threads=2,
            )
        except TypeError:
            # older easyocr without thread-knob params
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
