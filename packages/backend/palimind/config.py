from __future__ import annotations

import json
import os
from pathlib import Path

# Paths relative to the project root where `pm init` is run
PALIMIND_DIR = ".palimind"
CONFIG_FILE = "config.json"
DB_FILE = "index.db"

# Default application settings
DEFAULTS = {
    # NOTE: must be an Ollama model tag that is actually installed. HuggingFace
    # repo ids (e.g. "BAAI/bge-m3") are NOT valid Ollama tags and cause every
    # embed call to fail with "model not found". `bge-m3` is the 1024-dim
    # multilingual model (strong accuracy); `nomic-embed-text` is the lighter
    # 768-dim fallback.
    "embed_model": "bge-m3",
    "embed_dim": 1024,  # Vector dimension of embed_model (1024 bge-m3, 768 nomic)
    "chat_model": "gemma4:e2b",
    "vision_model": "llava",  # Ollama multimodal model used to caption images
    "chunk_size": 1500,
    "chunk_overlap": 200,
    "video_chunk_chars": 800,  # transcript chunk size for videos (chars)
    "turbovec_bit_width": 4,  # 2 or 4 — compression vs accuracy trade-off (legacy, unused)
    "vector_quantization": "none",  # "none" (float32), "sq8" (8-bit scalar), or "pq" (product quant)
    "summarise": False,  # Generate per-file summaries at index time
    "summary_max_chars": 8000,  # Characters fed to the summariser (truncated)
    "index_workers": 8,  # Files processed concurrently during indexing
    "index_batch_size": 5,  # Files per streaming batch (commit after each batch)
    # Knowledge-graph build runs AFTER indexing completes (non-blocking). Set
    # false to skip the extra LLM entity-extraction pass entirely.
    "build_graph": True,
    # Hard cap on tokens generated per graph entity-extraction call. The LLM
    # only needs a short JSON object; 2048 wasted wall-clock time.
    "graph_num_predict": 512,
    # Directories skipped by the crawler (matched by name at any depth).
    "ignore_dirs": [
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        "dist",
        "build",
        "target",
        "out",
        "coverage",
        "site-packages",
        "vendor",
        ".git",
        ".palimind",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".cache",
        ".tox",
    ],
    "retrieval_limit": 10,  # Number of chunks returned per retrieval call
    "context_token_budget": 8000,  # Maximum tokens assembled into LLM context
    "num_ctx": 16384,  # Ollama context window; must cover context_token_budget + prompt overhead
    "comparison_chunks_per_doc": 4,  # Chunks retrieved per document in comparison mode
    # Cross-encoder reranking is opt-in: on CPU it can dominate query latency
    # (tens of seconds for a warm cache). Enable per workspace or per query
    # when accuracy matters more than speed.
    "rerank": False,
    # Existing configs written before reranking became opt-in still contain
    # "rerank": true. This marker lets load_config disable that legacy value
    # unless the user explicitly opts back in.
    "rerank_opt_in": False,
    "rerank_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",  # small/fast CPU model
    "query_rewrite": True,  # LLM query rewriting at retrieval time
    "auto_reindex": False,  # Watcher auto-reindexes on file change (CPU/GIL heavy; off = manual Sync)
    "video_extensions": [".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"],
    "video_whisper_model": "base",  # Whisper tier for offline video transcription
    "video_chunk_seconds": 90,  # Max transcript chunk duration in seconds
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
    "moe_sub_mode": "default",  # "default", "moe", or "deep_research"
    "deep_research_model": "",  # model for deep research orchestrator (falls back to chat_model)
    "stt_whisper_model": "base.en",  # faster-whisper model for mic dictation
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
    if path.exists():
        with path.open() as f:
            data = json.load(f)
        merged = {**DEFAULTS, **data}
    else:
        merged = dict(DEFAULTS)
    # Migration: the old default was `rerank: true`. Treat configs without the
    # new opt-in marker as "off" so existing workspaces stop paying the CPU
    # cross-encoder cost on every query.
    if not merged.get("rerank_opt_in"):
        merged["rerank"] = False
    env_rerank = os.environ.get("PALIMIND_RERANK", "").strip().lower()
    if env_rerank:
        enabled = env_rerank in ("1", "true", "yes", "on")
        merged["rerank"] = enabled
        merged["rerank_opt_in"] = enabled
    return merged


def write_default_config(root: Path) -> None:
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    with path.open("w") as f:
        json.dump(DEFAULTS, f, indent=2)


def save_config(root: Path, config: dict) -> None:
    """Persist a merged config dict to the workspace config.json."""
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    path = config_path(root)
    with path.open("w") as f:
        json.dump({**DEFAULTS, **config}, f, indent=2)


GLOBAL_CONFIG_PATH = Path.home() / ".palimind_global.json"


def load_global_config() -> dict:
    """Load user-level config (~/.palimind_global.json) merged over defaults.

    Used by global-scope features (global chat, global agents) that operate
    outside any knowledge base.
    """
    config = dict(DEFAULTS)
    try:
        if GLOBAL_CONFIG_PATH.exists():
            data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
            for key, value in data.items():
                if value not in (None, ""):
                    config[key] = value
    except Exception:
        pass
    if not config.get("rerank_opt_in"):
        config["rerank"] = False
    env_rerank = os.environ.get("PALIMIND_RERANK", "").strip().lower()
    if env_rerank:
        enabled = env_rerank in ("1", "true", "yes", "on")
        config["rerank"] = enabled
        config["rerank_opt_in"] = enabled
    return config
