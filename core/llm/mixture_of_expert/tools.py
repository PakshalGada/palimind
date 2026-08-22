from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# ── per-run context (set by the orchestrator) ────────────────────────────

_tool_context: dict[str, Any] = {"root": None, "ollama_url": "", "chat_model": "", "light_model": ""}
_context_lock = threading.Lock()


def set_tool_context(
    root: Path | None,
    ollama_url: str = "",
    chat_model: str = "",
    light_model: str = "",
) -> None:
    with _context_lock:
        _tool_context.update(
            {
                "root": root,
                "ollama_url": ollama_url,
                "chat_model": chat_model,
                "light_model": light_model,
            }
        )


def _get_context() -> dict[str, Any]:
    with _context_lock:
        return dict(_tool_context)


def _workspace_root() -> Path | None:
    return _get_context().get("root")


# ── sandbox helpers ───────────────────────────────────────────────────────

MAX_READ_BYTES = 256_000  # 256 KB per file read
MAX_WRITE_BYTES = 512_000


def _resolve_in_workspace(path: str) -> Path | None:
    """Resolve *path* and confine it to the workspace root; None if outside."""
    root = _workspace_root()
    if root is None:
        p = Path(path).resolve()
        return p  # no workspace configured — allow (legacy behaviour)
    p = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    return p


# ── web tools ─────────────────────────────────────────────────────────────


def web_search(query: str, max_results: int = 4) -> str:
    from core.web_search import perform_web_search
    return perform_web_search(query, max_results=max_results)


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a specific URL and return its extracted readable content."""
    from core.web_search import fetch_url_content
    return fetch_url_content(url, max_chars=max_chars)


# ── workspace knowledge tools ─────────────────────────────────────────────


def document_search(query: str, limit: int = 6) -> str:
    """Search the user's indexed documents (semantic + keyword hybrid)."""
    ctx = _get_context()
    root = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for document search."

    from core.config import load_config
    from core.embedder import generate_embedding
    from core.storage.db import fts_search, get_connection
    from core.storage.vector_store import search as vector_search

    config = load_config(root)
    ollama_url = ctx.get("ollama_url") or config.get(
        "ollama_base_url", "http://localhost:11434"
    )
    embed_model = config.get("embed_model", "nomic-embed-text")

    seen: set[int] = set()
    results: list[dict] = []

    try:
        qvec = generate_embedding(query, ollama_url, embed_model, root=root)
        if qvec:
            for r in vector_search(root, qvec, limit=limit):
                cid = r.get("chunk_db_id")
                if cid is not None and cid not in seen:
                    seen.add(cid)
                    r["search_type"] = "semantic"
                    results.append(r)
    except Exception as e:
        results.append({"content": f"[semantic search unavailable: {e}]", "file_path": ""})

    try:
        conn = get_connection(root)
        try:
            for r in fts_search(conn, query, limit=limit):
                cid = r.get("chunk_db_id")
                if cid is not None and cid not in seen:
                    seen.add(cid)
                    r["search_type"] = "keyword"
                    results.append(r)
        finally:
            conn.close()
    except Exception as e:
        results.append({"content": f"[keyword search unavailable: {e}]", "file_path": ""})

    if not results:
        return f"No indexed documents matched '{query}'."

    parts = [f"=== DOCUMENT SEARCH RESULTS FOR: '{query}' ===\n"]
    for idx, r in enumerate(results[:limit], start=1):
        fp = r.get("file_path", "") or "unknown"
        sec = r.get("section_title", "") or r.get("main_section", "")
        sec_str = f" → {sec}" if sec else ""
        parts.append(
            f"Source [{idx}] ({r.get('search_type', '')}): {fp}{sec_str}\n"
            f"{r.get('content', '')[:2000]}\n"
        )
    return "\n".join(parts) + "=" * 39 + "\n"


def memory_search(query: str, limit: int = 3) -> str:
    """Search past conversation memory (long-term episodic store)."""
    ctx = _get_context()
    root = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for memory search."

    try:
        from core.config import load_config
        from core.embedder import generate_embeddings_batch
        from core.storage.chat_store import search_chat_episodes

        config = load_config(root)
        ollama_url = ctx.get("ollama_url") or config.get(
            "ollama_base_url", "http://localhost:11434"
        )
        embed_model = config.get("embed_model", "nomic-embed-text")

        embs = generate_embeddings_batch([query], ollama_url, embed_model)
        if not embs or not embs[0]:
            return "No memory results found."
        episodes = search_chat_episodes(root, embs[0], limit=limit)
        if not episodes:
            return f"No past conversations matched '{query}'."
        lines = [f"- {ep.get('content', '').strip()[:600]}" for ep in episodes]
        return "=== RELEVANT PAST CONVERSATIONS ===\n" + "\n".join(lines)
    except Exception as e:
        return f"Memory search error: {e}"


# ── file tools (sandboxed to the workspace) ───────────────────────────────


def read_file(path: str) -> str:
    p = _resolve_in_workspace(path)
    if p is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not p.exists():
        return f"Error: file not found at {path}"
    if not p.is_file():
        return f"Error: {path} is not a file"
    try:
        data = p.read_bytes()[:MAX_READ_BYTES]
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file {path}: {e}"


def write_file(path: str, content: str) -> str:
    p = _resolve_in_workspace(path)
    if p is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return f"Error: content too large (max {MAX_WRITE_BYTES} bytes)"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file {path}: {e}"


def list_files(path: str = ".") -> str:
    base = _resolve_in_workspace(path)
    if base is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not base.exists():
        return f"Error: path not found at {path}"
    if not base.is_dir():
        return f"Error: {path} is not a directory"
    try:
        items = []
        for entry in sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if entry.name.startswith("."):
                continue
            t = "directory" if entry.is_dir() else "file"
            items.append(f"{t}: {entry.name}")
        return "\n".join(items) if items else "(empty directory)"
    except Exception as e:
        return f"Error listing files: {e}"


# ── compute tools ─────────────────────────────────────────────────────────


def run_python(code: str, timeout: int = 15) -> str:
    """Execute Python code in an isolated subprocess with a timeout.

    Prints/stdout are captured and returned.
    """
    import subprocess
    import sys
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name
        try:
            proc = subprocess.run(
                [sys.executable, "-I", tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            if proc.returncode != 0:
                return f"Error (exit {proc.returncode}):\n{err[-2000:]}"
            return out[-4000:] if out else "Code executed successfully (no output)"
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        return f"Error: code execution timed out after {timeout}s"
    except Exception as e:
        return f"Error executing code: {e}"


# ── summarization tool ────────────────────────────────────────────────────


def summarize(text: str, max_chars: int = 1000) -> str:
    """Summarize long text with the light model."""
    if len(text) <= max_chars:
        return text
    ctx = _get_context()
    root = _workspace_root()
    model = ctx.get("light_model") or ctx.get("chat_model")
    if not model:
        return text[:max_chars] + "\n...[truncated]"

    ollama_url = ctx.get("ollama_url")
    if root is not None and not ollama_url:
        from core.config import load_config
        ollama_url = load_config(root).get("ollama_base_url", "http://localhost:11434")
    if not ollama_url:
        return text[:max_chars] + "\n...[truncated]"

    from core.llm.mixture_of_expert.llm import llm_chat_safe

    result = llm_chat_safe(
        [
            {
                "role": "user",
                "content": (
                    "Summarize the following content in under "
                    f"{max_chars} characters, keeping key facts and numbers:\n\n{text[:8000]}"
                ),
            }
        ],
        model,
        ollama_url,
        temperature=0.1,
        num_predict=400,
        error_prefix="[summarize error",
    )
    return result["content"] or text[:max_chars]


# ── registry ──────────────────────────────────────────────────────────────


TOOL_REGISTRY: dict[str, dict] = {
    "web_search": {
        "fn": web_search,
        "description": "Search the web using DuckDuckGo and fetch page content for top results.",
        "parameters": {
            "query": "The search query string",
            "max_results": "Optional: maximum number of results (default 4)",
        },
    },
    "fetch_url": {
        "fn": fetch_url,
        "description": "Fetch a specific URL and extract its readable page content.",
        "parameters": {
            "url": "The full URL to fetch (http/https)",
            "max_chars": "Optional: maximum characters to return (default 4000)",
        },
    },
    "document_search": {
        "fn": document_search,
        "description": "Search the user's indexed workspace documents (semantic + keyword).",
        "parameters": {
            "query": "The search query",
            "limit": "Optional: maximum chunks to return (default 6)",
        },
    },
    "memory_search": {
        "fn": memory_search,
        "description": "Search past conversation memory for relevant episodes.",
        "parameters": {
            "query": "The search query",
            "limit": "Optional: maximum episodes (default 3)",
        },
    },
    "read_file": {
        "fn": read_file,
        "description": "Read a file from the workspace (sandboxed to the active field).",
        "parameters": {
            "path": "Absolute or workspace-relative path to the file",
        },
    },
    "write_file": {
        "fn": write_file,
        "description": "Write content to a file in the workspace (sandboxed to the active field).",
        "parameters": {
            "path": "Absolute or workspace-relative path to the file",
            "content": "Text content to write",
        },
    },
    "list_files": {
        "fn": list_files,
        "description": "List files and directories at a given workspace path.",
        "parameters": {
            "path": "Optional: directory path (default '.')",
        },
    },
    "run_python": {
        "fn": run_python,
        "description": "Execute Python code in an isolated subprocess. stdout is returned.",
        "parameters": {
            "code": "Python code to execute",
            "timeout": "Optional: timeout in seconds (default 15)",
        },
    },
    "summarize": {
        "fn": summarize,
        "description": "Summarize long text using the light model.",
        "parameters": {
            "text": "The text to summarize",
            "max_chars": "Optional: target length in characters (default 1000)",
        },
    },
}


def get_tool_names() -> list[str]:
    return sorted(TOOL_REGISTRY.keys())


def call_tool(name: str, **kwargs: Any) -> str:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"Error: unknown tool '{name}'. Available: {', '.join(get_tool_names())}"
    try:
        return str(entry["fn"](**kwargs))
    except TypeError as e:
        return f"Tool '{name}' argument error: {e}"
    except Exception as e:
        return f"Tool '{name}' error: {e}"


AVAILABLE_TOOLS_DESC = "\n".join(
    f"- {name}: {info['description']}"
    for name, info in sorted(TOOL_REGISTRY.items())
)
