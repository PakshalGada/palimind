from __future__ import annotations

import json
from pathlib import Path

# Paths relative to the project root where `pm init` is run
PALIMIND_DIR = ".palimind"
CONFIG_FILE = "config.json"
DB_FILE = "index.db"

# Default application settings
DEFAULTS = {
    "embed_model": "nomic-embed-text",
    "chat_model": "gemma4:e2b",
    "chunk_size": 3000,
    "chunk_overlap": 500,
    "turbovec_bit_width": 4,  # 2 or 4 — compression vs accuracy trade-off
    "summarise": True,        # Generate per-file summaries at index time
    "summary_max_chars": 8000,  # Characters fed to the summariser (truncated)
    "extract_financials": True,  # Extract financial facts at index time (financial docs)
    "extract_timeline": True,    # Extract timeline events at index time
    "retrieval_limit": 10,         # Number of chunks returned per retrieval call
    "context_token_budget": 8000,  # Maximum tokens assembled into LLM context
    "comparison_chunks_per_doc": 4,  # Chunks retrieved per document in comparison mode
    "rerank": True,                # Rerank fused results with a local cross-encoder
    "rerank_model": "BAAI/bge-reranker-base",  # Local cross-encoder for reranking
    "query_rewrite": True,         # LLM query rewriting at retrieval time
    "video_extensions": [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"],
    "video_whisper_model": "base",  # Whisper tier for offline video transcription
    "video_chunk_seconds": 90,      # Max transcript chunk duration in seconds
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
    "ollama_base_url": "http://localhost:11434",
    "light_model": "",  # smaller/faster model for graph building & entity extraction; falls back to chat_model
    "moe_orchestrator_model": "",
    "moe_worker_model": "",
    "moe_sub_mode": "default",  # "default" or "moe"
    "thinking_model": "",  # model used when the user toggles Think mode; falls back to chat_model
    "persona_name": "",
    "persona_system_prompt": "",
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
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    with path.open("w") as f:
        json.dump(DEFAULTS, f, indent=2)
