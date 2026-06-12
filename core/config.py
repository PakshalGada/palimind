from __future__ import annotations

import json
import os
from pathlib import Path

# Paths relative to the project root where `pm init` is run
PALIMIND_DIR = ".palimind"
CONFIG_FILE = "config.json"
DB_FILE = "index.db"
APP_NAME = "Palimind"

# Default application settings
DEFAULTS = {
    "embed_model": "nomic-embed-text",
    "chat_model": "gemma4:e4b",
    "vision_model": "llava",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "turbovec_bit_width": 4,  # 2 or 4 — compression vs accuracy trade-off
    "summarise": True,        # Generate per-file summaries at index time
    "summary_max_chars": 8000,  # Characters fed to the summariser (truncated)
    "extract_financials": True,  # Extract financial facts at index time (financial docs)
    "extract_timeline": True,    # Extract timeline events at index time
    "retrieval_limit": 10,         # Number of chunks returned per retrieval call
    "context_token_budget": 8000,  # Maximum tokens assembled into LLM context
    "comparison_chunks_per_doc": 4,  # Chunks retrieved per document in comparison mode
    "extensions": [
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".go",
        ".rs",
        ".c",
        ".cpp",
        ".h",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".html",
        ".rst",
    ],
    "doc_extensions": [".pdf", ".docx", ".pptx", ".xlsx"],
    "image_extensions": [".png", ".jpg", ".jpeg", ".webp"],
    "ollama_base_url": "https://huge-parks-burn.loca.lt",
}


def palimind_dir(root: Path) -> Path:
    return root / PALIMIND_DIR


def config_path(root: Path) -> Path:
    return palimind_dir(root) / CONFIG_FILE


def db_path(root: Path) -> Path:
    return palimind_dir(root) / DB_FILE


def app_data_dir() -> Path:
    """Return Palimind's global user-data directory."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME.lower()
    return Path.home() / ".palimind"


def app_config_dir() -> Path:
    return app_data_dir() / "config"


def app_cache_dir() -> Path:
    return app_data_dir() / "cache"


def app_logs_dir() -> Path:
    return app_data_dir() / "logs"


def load_config(root: Path) -> dict:
    path = config_path(root)
    if not path.exists():
        return dict(DEFAULTS)
    with path.open() as f:
        data = json.load(f)
    return {**DEFAULTS, **data}


def write_default_config(root: Path) -> None:
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    with path.open("w") as f:
        json.dump(DEFAULTS, f, indent=2)
