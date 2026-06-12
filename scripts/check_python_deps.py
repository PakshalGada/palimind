"""Print missing Palimind Python dependency specs as JSON."""
from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path

MODULE_NAMES = {
    "pymupdf": "fitz",
    "python-pptx": "pptx",
    "pillow": "PIL",
    "sentence-transformers": "sentence_transformers",
    "faster-whisper": "faster_whisper",
    "kokoro-onnx": "kokoro_onnx",
}


def package_name(spec: str) -> str:
    for sep in ("[", "<", ">", "=", "~", "!", ";"):
        spec = spec.split(sep, 1)[0]
    return spec.strip()


def main() -> int:
    root = Path(sys.argv[1])
    include_build = sys.argv[2].lower() == "true"

    with (root / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)

    deps = list(data.get("project", {}).get("dependencies", []))
    if include_build:
        deps.append("pyinstaller")

    missing = []
    for dep in deps:
        name = package_name(dep)
        module = MODULE_NAMES.get(name.lower(), name.replace("-", "_"))
        if importlib.util.find_spec(module) is None:
            missing.append(dep)

    print(json.dumps(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
