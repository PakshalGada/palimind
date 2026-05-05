import json
from pathlib import Path

PALIMIND_DIR = ".palimind"
CONFIG_FILE = "config.json"
DB_FILE = "index.db"

DEFAULTS = {
    "embed_model": "nomic-embed-text",
    "chat_model": "llama3",
    "chunk_size": 1000,
    "chunk_overlap": 200,
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
        ".pdf",
        ".docx",
        ".pptx",
    ],
}


def palimind_dir(root: Path) -> Path:
    return root / PALIMIND_DIR


def config_path(root: Path) -> Path:
    return palimind_dir(root) / CONFIG_FILE


def db_path(root: Path) -> Path:
    return palimind_dir(root) / DB_FILE


def load_config(root: Path) -> dict:
    path = config_path(root)
    if not path.exists():
        return dict(DEFAULTS)
    with path.open() as f:
        data = json.load(f)
    return {**DEFAULTS, **data}


def write_default_config(root: Path) -> None:
    path = config_path(root)
    with path.open("w") as f:
        json.dump(DEFAULTS, f, indent=2)
