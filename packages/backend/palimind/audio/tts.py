import io
import urllib.request
from pathlib import Path

# Cache directory for ONNX files
CACHE_DIR = Path.home() / ".palimind_audio"
MODEL_PATH = CACHE_DIR / "kokoro-v0_19.onnx"
VOICES_PATH = CACHE_DIR / "voices.bin"

_tts = None


def download_model_files():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Official GitHub Releases URLs for Kokoro ONNX
    model_url = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
    voices_url = (
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"
    )

    # Clean up empty or broken files from previous failed download attempts
    for path in (MODEL_PATH, VOICES_PATH):
        if path.exists() and path.stat().st_size < 1024:
            print(f"Removing invalid file (size < 1KB): {path}")
            try:
                path.unlink()
            except Exception as e:
                print(f"Failed to remove invalid file: {e}")

    if not MODEL_PATH.exists():
        print(f"Downloading Kokoro TTS model to {MODEL_PATH}...")
        _download(model_url, MODEL_PATH, "voice model")
    if not VOICES_PATH.exists():
        print(f"Downloading Kokoro voices to {VOICES_PATH}...")
        _download(voices_url, VOICES_PATH, "voice data")


def _download(url: str, dest: Path, label: str) -> None:
    """Download with progress reported to the setup-status banner."""
    from palimind import setup_status

    def hook(blocknum: int, blocksize: int, totalsize: int) -> None:
        if totalsize and totalsize > 0:
            done = min(blocknum * blocksize, totalsize)
            setup_status.update(
                "tts",
                progress=done / totalsize,
                message=f"{label}: {done // 1048576} / {totalsize // 1048576} MB",
            )
        else:
            setup_status.update("tts", message=f"Downloading {label}…")

    urllib.request.urlretrieve(url, str(dest), reporthook=hook)


def get_tts():
    global _tts
    if _tts is None:
        from palimind import setup_status

        setup_status.start("tts", "Preparing voice model (first run)")
        try:
            from kokoro_onnx import Kokoro

            # Ensure model files are available
            if not MODEL_PATH.exists() or not VOICES_PATH.exists():
                download_model_files()

            setup_status.update("tts", message="Loading voice model…")
            _tts = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
            print("Kokoro ONNX initialized successfully.")
        except Exception as e:
            print(
                f"Failed to initialize Kokoro ONNX: {e}. Speech will be synthesized with fallback."
            )
        finally:
            setup_status.finish("tts")
    return _tts


def text_to_speech_bytes(text: str, voice: str = "af_bella") -> bytes | None:
    """Synthesizes text into WAV bytes using Kokoro ONNX."""
    engine = get_tts()
    if engine is None:
        return None

    try:
        # soundfile is an optional dependency of the speech feature; import it
        # lazily so importing the package never requires it.
        import soundfile as sf

        # Generate raw float32 array
        samples, sample_rate = engine.create(text, voice=voice, speed=1.0, lang="en-us")

        # Write to WAV bytes in memory
        out_buf = io.BytesIO()
        sf.write(out_buf, samples, sample_rate, format="WAV", subtype="PCM_16")
        return out_buf.getvalue()
    except Exception as e:
        print(f"TTS Synthesis error: {e}")
        return None
