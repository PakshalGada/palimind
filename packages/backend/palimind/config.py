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
    # Optional learned-sparse / late-interaction retrieval. Both require the
    # `FlagEmbedding` package and a local bge-m3 checkpoint (they are not
    # exposed by the Ollama embed endpoint); they degrade to a no-op otherwise.
    "sparse_retrieval": False,
    "sparse_model": "BAAI/bge-m3",
    "colbert_rerank": False,
    "colbert_candidates": 50,
    "chat_model": "gemma4:e2b",
    "vision_model": "llava",  # Ollama multimodal model used to caption images
    # Child chunks are deliberately small: retrieval matches the precise
    # passage, then the parent section is assembled for the LLM. Larger values
    # dilute embeddings and crowd the context window.
    "chunk_size": 700,
    "chunk_overlap": 120,
    # Child-chunk size used by the indexer. Prefer these keys when migrating
    # existing workspaces (their legacy chunk_size/chunk_overlap stay valid
    # for callers that still read them).
    "child_chunk_size": 700,
    "child_chunk_overlap": 120,
    # Bump when chunking semantics change; an index stamped with an older
    # value is rebuilt on the next update so every chunk uses the new layout.
    "chunker_version": 3,
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
    # Over-fetch depth per query variant before fusion/rerank. RRF on a deep
    # candidate pool is what makes a reranker or MMR selection useful.
    "retrieval_candidate_depth": 50,
    # Small-to-big retrieval: match a child chunk, then hand the LLM the whole
    # parent section (bounded so a huge section cannot crowd the context).
    "parent_retrieval": True,
    "parent_max_tokens": 1500,
    # Embedding MMR diversity selection (falls back to lexical dedupe when the
    # stored embeddings are unavailable).
    "mmr": True,
    "mmr_lambda": 0.7,
    "mmr_per_file_cap": 4,
    # Search the per-file summary index to boost documents that match the
    # question as a whole ("which report covers X?").
    "summary_search": True,
    # Agentic RAG for document mode: "auto" routes complex multi-part /
    # multi-hop questions through a plan → parallel retrieve → verify loop.
    "agentic_rag": "auto",  # auto | off | always
    "agentic_rag_max_subqueries": 6,
    "agentic_rag_max_rounds": 2,
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
    # Maximum time to wait for rewritten query variants. Local 7B/9B models
    # routinely need more than this; waiting longer made every query slower
    # without improving results, so the base variants win the race by default.
    "query_rewrite_timeout": 0.6,
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
    "search_provider": "auto",  # auto | ddg | searxng
    "searxng_url": "",  # local SearXNG base URL; empty uses the env/default
}


# Parsed config cache keyed by (path, mtime_ns, size). Retrieval calls
# load_config() on every query; re-reading and merging the same JSON was pure
# overhead once the workspace settles.
_CONFIG_CACHE: dict[tuple[str, int, int], dict] = {}


def _embedding_dim_for_model(model_id: str) -> int:
    """Best-effort known output dimension for an embedding model name."""
    try:
        from palimind.model_capabilities import infer_from_name

        return int(infer_from_name(model_id).embedding_dim or 0)
    except Exception:
        return 0


def palimind_dir(root: Path) -> Path:
    return root / PALIMIND_DIR


def config_path(root: Path) -> Path:
    return palimind_dir(root) / CONFIG_FILE


def db_path(root: Path) -> Path:
    return palimind_dir(root) / DB_FILE


def load_config(root: Path) -> dict:
    path = config_path(root)
    if path.exists():
        try:
            stat = path.stat()
            cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
            cached = _CONFIG_CACHE.get(cache_key)
            if cached is not None:
                return dict(cached)
        except OSError:
            cache_key = None
            stat = None
        with path.open() as f:
            data = json.load(f)
        merged = {**DEFAULTS, **data}
        if cache_key is not None:
            if len(_CONFIG_CACHE) > 64:
                _CONFIG_CACHE.clear()
            _CONFIG_CACHE[cache_key] = dict(merged)
    else:
        merged = dict(DEFAULTS)
    # Migration: the old default was `rerank: true`. Treat configs without the
    # new opt-in marker as "off" so existing workspaces stop paying the CPU
    # cross-encoder cost on every query.
    if not merged.get("rerank_opt_in"):
        merged["rerank"] = False
    # Keep embed_dim in sync with the model family. A stale dim (for example
    # embed_dim=1024 after switching to nomic-embed-text) used to reject a
    # perfectly healthy 768-dim index and disable semantic search.
    known_dim = _embedding_dim_for_model(str(merged.get("embed_model") or ""))
    if known_dim and int(merged.get("embed_dim") or 0) != known_dim:
        merged["embed_dim"] = known_dim
    env_rerank = os.environ.get("PALIMIND_RERANK", "").strip().lower()
    if env_rerank:
        enabled = env_rerank in ("1", "true", "yes", "on")
        merged["rerank"] = enabled
        merged["rerank_opt_in"] = enabled
    return merged


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write via temp file + ``os.replace``: a crash mid-write must never leave
    a truncated config.json, which makes every load_config() call raise."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def write_default_config(root: Path) -> None:
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(config_path(root), DEFAULTS)


def save_config(root: Path, config: dict) -> None:
    """Persist a merged config dict to the workspace config.json."""
    p_dir = palimind_dir(root)
    p_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(config_path(root), {**DEFAULTS, **config})


GLOBAL_CONFIG_PATH = Path.home() / ".palimind_global.json"


def save_global_config(changes: dict) -> dict:
    """Merge *changes* into the user-level config and persist atomically."""
    data = load_global_config()
    data.update(changes)
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(GLOBAL_CONFIG_PATH, data)
    return data


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
