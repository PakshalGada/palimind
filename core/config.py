import json
import os
from pathlib import Path

# Paths relative to the project root where `pm init` is run
PALIMIND_DIR = ".palimind"
CONFIG_FILE = "config.json"
DB_FILE = "index.db"

# Default application settings
DEFAULTS = {
    "embed_model": "nomic-embed-text",
    "chat_model": "llama3",
    "vision_model": "llava",
    "chunk_size": 1000,
    "chunk_overlap": 200,
    "extensions": [
        ".txt", ".md", ".py", ".js", ".ts", ".go", ".rs", ".c", ".cpp", ".h",
        ".json", ".yaml", ".yml", ".toml", ".csv", ".html", ".rst"
    ],
    "doc_extensions": [".pdf", ".docx", ".pptx", ".xlsx"],
    "image_extensions": [".png", ".jpg", ".jpeg", ".webp"],
    "ollama_base_url": "http://localhost:11434"
}

def palimind_dir(root: Path) -> Path:
    return root / PALIMIND_DIR

def config_path(root: Path) -> Path:
    return palimind_dir(root) / CONFIG_FILE

def db_path(root: Path) -> Path:
    return palimind_dir(root) / DB_FILE

def lance_db_path(root: Path) -> Path:
    return palimind_dir(root) / "vector_store.lance"

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
