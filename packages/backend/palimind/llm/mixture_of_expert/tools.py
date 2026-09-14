from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

# ── per-run context (set by the orchestrator) ────────────────────────────

_tool_context: dict[str, Any] = {
    "root": None,
    "extra_roots": [],
    "ollama_url": "",
    "chat_model": "",
    "light_model": "",
}
_context_lock = threading.Lock()


def set_tool_context(
    root: Path | None,
    ollama_url: str = "",
    chat_model: str = "",
    light_model: str = "",
    extra_roots: list[Path] | None = None,
) -> None:
    with _context_lock:
        _tool_context.update(
            {
                "root": root,
                "extra_roots": list(extra_roots or []),
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


def _extra_roots() -> list[Path]:
    return list(_get_context().get("extra_roots") or [])


# ── sandbox helpers ───────────────────────────────────────────────────────

MAX_READ_BYTES = 256_000  # 256 KB per file read
MAX_WRITE_BYTES = 512_000

_SKIP_DIRS = {
    ".git",
    ".palimind",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    ".idea",
    ".vscode",
}


def _resolve_in_workspace(path: str) -> Path | None:
    """Resolve *path* and confine it to the workspace root(s); None if outside."""
    roots = [r for r in [_workspace_root(), *_extra_roots()] if r is not None]
    if not roots:
        p = Path(path).resolve()
        return p  # no workspace configured — allow (legacy behaviour)
    p = (roots[0] / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    for root in roots:
        try:
            p.relative_to(root.resolve())
            return p
        except ValueError:
            continue
    return None


def _is_skipped(p: Path, base: Path) -> bool:
    """Skip hidden/vendor directories when recursing under *base*."""
    try:
        rel = p.relative_to(base)
    except ValueError:
        return True
    return any(part.startswith(".") or part in _SKIP_DIRS for part in rel.parts[:-1])


# ── auto-reindex on write (debounced) ────────────────────────────────────

_reindex_lock = threading.Lock()
_reindex_timer: threading.Timer | None = None


def _schedule_reindex() -> None:
    """Debounced background reindex of the workspace after a file write.

    Opt-in via the field's ``auto_reindex`` config (default off) because a
    full reindex is CPU/GIL-heavy and can starve the API server. Bounded:
    only one pending reindex timer is kept, so bursts of writes cannot create
    an unbounded thread explosion.
    """
    root = _workspace_root()
    if root is None:
        return
    if not (root / ".palimind" / "index.db").exists():
        return
    try:
        from palimind.config import load_config

        if not load_config(root).get("auto_reindex", False):
            return
    except Exception:
        return
    global _reindex_timer
    with _reindex_lock:
        if _reindex_timer is not None:
            return  # a reindex is already scheduled
        _reindex_timer = threading.Timer(2.0, _run_reindex, args=(root,))
        _reindex_timer.daemon = True
        _reindex_timer.start()


def _run_reindex(root: Path) -> None:
    global _reindex_timer
    with _reindex_lock:
        _reindex_timer = None  # allow new writes to schedule a fresh reindex
    try:
        from palimind.config import load_config
        from palimind.document.graph import build_doc_graph_incremental
        from palimind.rag.indexing import update_index
        from palimind.storage.db import INDEX_WRITE_LOCK

        if INDEX_WRITE_LOCK.locked():
            print("[tools] auto-reindex skipped — another reindex is running")
            return

        update_index(root)
        cfg = load_config(root)
        build_doc_graph_incremental(root, cfg.get("ollama_base_url", "http://localhost:11434"))
        print(f"[tools] auto-reindexed workspace {root}")
    except Exception as e:
        print(f"[tools] auto-reindex failed: {e}")


# ── web tools ─────────────────────────────────────────────────────────────


def web_search(query: str, max_results: int = 4) -> str:
    from palimind.core.web_search import perform_web_search

    return perform_web_search(query, max_results=max_results)


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a specific URL and return its extracted readable content."""
    from palimind.core.web_search import fetch_url_content

    return fetch_url_content(url, max_chars=max_chars)


# ── workspace knowledge tools ─────────────────────────────────────────────


def document_search(query: str, limit: int = 6) -> str:
    """Search the user's indexed documents (hybrid semantic + BM25 + rerank)."""
    ctx = _get_context()
    root = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for document search."

    from palimind.config import load_config
    from palimind.rag.retrieve import hybrid_search

    config = load_config(root)
    ollama_url = ctx.get("ollama_url") or config.get("ollama_base_url", "http://localhost:11434")
    embed_model = config.get("embed_model", "nomic-embed-text")
    light_model = (
        ctx.get("light_model") or config.get("light_model", "") or config.get("chat_model", "")
    )

    try:
        context = hybrid_search(
            root,
            query,
            limit=limit,
            ollama_url=ollama_url,
            embed_model=embed_model,
            light_model=light_model,
            rerank_enabled=bool(config.get("rerank", True)),
            rerank_model=config.get("rerank_model") or "BAAI/bge-reranker-base",
            query_rewrite_enabled=bool(config.get("query_rewrite", True)),
            context_token_budget=config.get("context_token_budget"),
        )
    except Exception as e:
        return f"[document search unavailable: {e}]"

    results = context.get("results", [])
    if not results:
        return f"No indexed documents matched '{query}'."

    parts = [f"=== DOCUMENT SEARCH RESULTS FOR: '{query}' ===\n"]
    for idx, r in enumerate(results, start=1):
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
        from palimind.config import load_config
        from palimind.core.embedder import generate_embeddings_batch
        from palimind.storage.chat_store import search_chat_episodes

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
    except Exception as e:
        return f"Error writing file {path}: {e}"
    _schedule_reindex()
    return f"Successfully wrote {len(content)} bytes to {path}"


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


def glob_files(pattern: str, path: str = ".", max_results: int = 200) -> str:
    """Recursively list workspace files whose path matches a glob pattern."""
    base = _resolve_in_workspace(path)
    if base is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not base.is_dir():
        return f"Error: path not found at {path}"
    matches: list[str] = []
    try:
        for p in base.rglob(pattern):
            if p.is_dir() or _is_skipped(p, base):
                continue
            matches.append(str(p.relative_to(base)))
            if len(matches) >= max_results:
                break
    except Exception as e:
        return f"Error globbing files: {e}"
    return "\n".join(matches) if matches else f"No files match '{pattern}' under {path}"


def grep_files(pattern: str, path: str = ".", max_results: int = 50) -> str:
    """Search file contents inside the workspace (recursive, case-insensitive)."""
    import re as _re

    base = _resolve_in_workspace(path)
    if base is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not base.is_dir():
        return f"Error: path not found at {path}"
    try:
        rx = _re.compile(pattern, _re.IGNORECASE)
    except _re.error as e:
        return f"Error: invalid pattern: {e}"

    matches: list[str] = []
    scanned = 0
    try:
        for p in base.rglob("*"):
            if not p.is_file() or _is_skipped(p, base):
                continue
            scanned += 1
            if scanned > 1000:
                break
            try:
                text = p.read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    matches.append(f"{p.relative_to(base)}:{lineno}: {line.strip()[:160]}")
                    if len(matches) >= max_results:
                        break
            if len(matches) >= max_results:
                break
    except Exception as e:
        return f"Error searching files: {e}"
    if not matches:
        return f"No matches for '{pattern}' under {path}"
    return "\n".join(matches)


def search_replace(path: str, old_string: str, new_string: str, count: int = 1) -> str:
    """Surgical in-file replacement (surgical edits instead of full overwrite)."""
    p = _resolve_in_workspace(path)
    if p is None:
        return f"Error: access denied — '{path}' is outside the workspace"
    if not p.is_file():
        return f"Error: file not found at {path}"
    if not old_string:
        return "Error: old_string is required"
    try:
        text = p.read_text("utf-8")
    except Exception as e:
        return f"Error reading file {path}: {e}"
    if old_string not in text:
        return f"Error: 'old_string' not found in {path}"
    occurrences = text.count(old_string)
    n = max(1, min(int(count or 1), 100))
    replaced = min(n, occurrences)
    new_text = text.replace(old_string, new_string, replaced)
    if len(new_text.encode("utf-8")) > MAX_WRITE_BYTES:
        return f"Error: result too large (max {MAX_WRITE_BYTES} bytes)"
    try:
        p.write_text(new_text, "utf-8")
    except Exception as e:
        return f"Error writing file {path}: {e}"
    _schedule_reindex()
    return f"Replaced {replaced} of {occurrences} occurrence(s) of '{old_string}' in {path}"


# ── compute tools ─────────────────────────────────────────────────────────


def run_python(code: str, timeout: int = 15) -> str:
    """Execute Python code in an isolated subprocess with a timeout.

    Prints/stdout are captured and returned.
    """
    import subprocess
    import sys
    import tempfile

    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
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
        from palimind.config import load_config

        ollama_url = load_config(root).get("ollama_base_url", "http://localhost:11434")
    if not ollama_url:
        return text[:max_chars] + "\n...[truncated]"

    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

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


def _meta(tier: int, requires_approval: bool) -> dict[str, Any]:
    return {"tier": tier, "requires_approval": requires_approval}


TOOL_REGISTRY: dict[str, dict] = {
    "web_search": {
        "fn": web_search,
        "description": "Search the web using DuckDuckGo and fetch page content for top results.",
        "parameters": {
            "query": "The search query string",
            "max_results": "Optional: maximum number of results (default 4)",
        },
        "meta": _meta(1, False),
    },
    "fetch_url": {
        "fn": fetch_url,
        "description": "Fetch a specific URL and extract its readable page content.",
        "parameters": {
            "url": "The full URL to fetch (http/https)",
            "max_chars": "Optional: maximum characters to return (default 4000)",
        },
        "meta": _meta(1, False),
    },
    "document_search": {
        "fn": document_search,
        "description": "Search the user's indexed workspace documents (semantic + keyword).",
        "parameters": {
            "query": "The search query",
            "limit": "Optional: maximum chunks to return (default 6)",
        },
        "meta": _meta(1, False),
    },
    "memory_search": {
        "fn": memory_search,
        "description": "Search past conversation memory for relevant episodes.",
        "parameters": {
            "query": "The search query",
            "limit": "Optional: maximum episodes (default 3)",
        },
        "meta": _meta(1, False),
    },
    "read_file": {
        "fn": read_file,
        "description": "Read a file from the workspace (sandboxed to the active field).",
        "parameters": {
            "path": "Absolute or workspace-relative path to the file",
        },
        "meta": _meta(1, False),
    },
    "write_file": {
        "fn": write_file,
        "description": "Write content to a file in the workspace (sandboxed to the active field).",
        "parameters": {
            "path": "Absolute or workspace-relative path to the file",
            "content": "Text content to write",
        },
        "meta": _meta(2, True),
    },
    "list_files": {
        "fn": list_files,
        "description": "List files and directories at a given workspace path.",
        "parameters": {
            "path": "Optional: directory path (default '.')",
        },
        "meta": _meta(1, False),
    },
    "glob_files": {
        "fn": glob_files,
        "description": "Recursively list workspace files matching a glob pattern (e.g. '**/*.py').",
        "parameters": {
            "pattern": "The glob pattern to match file paths",
            "path": "Optional: directory to search from (default '.')",
            "max_results": "Optional: max results (default 200)",
        },
        "meta": _meta(1, False),
    },
    "grep_files": {
        "fn": grep_files,
        "description": "Search file contents inside the workspace for a pattern (case-insensitive regex).",
        "parameters": {
            "pattern": "Regex or plain-text pattern to search for",
            "path": "Optional: directory to search from (default '.')",
            "max_results": "Optional: max matches (default 50)",
        },
        "meta": _meta(1, False),
    },
    "search_replace": {
        "fn": search_replace,
        "description": "Surgically replace occurrences of a string in a workspace file.",
        "parameters": {
            "path": "Absolute or workspace-relative path to the file",
            "old_string": "Exact text to find",
            "new_string": "Replacement text",
            "count": "Optional: number of occurrences to replace (default 1)",
        },
        "meta": _meta(2, True),
    },
    "run_python": {
        "fn": run_python,
        "description": "Execute Python code in an isolated subprocess. stdout is returned.",
        "parameters": {
            "code": "Python code to execute",
            "timeout": "Optional: timeout in seconds (default 15)",
        },
        "meta": _meta(2, True),
    },
    "summarize": {
        "fn": summarize,
        "description": "Summarize long text using the light model.",
        "parameters": {
            "text": "The text to summarize",
            "max_chars": "Optional: target length in characters (default 1000)",
        },
        "meta": _meta(1, False),
    },
}


def _register_plugin_tools() -> None:
    """Lazily merge plugin tools (run_shell, csv_query, sqlite_query,
    query_graph) into the registry so the UI and agent loop see them."""
    import importlib

    plugins = [
        ("run_shell", "palimind.agents.tools.shell-exec.tool", "run_shell"),
        ("csv_query", "palimind.agents.tools.csv-query.tool", "csv_query"),
        ("sqlite_query", "palimind.agents.tools.sqlite-query.tool", "sqlite_query"),
        ("query_graph", "palimind.agents.tools.knowledge-graph.tool", "query_graph"),
    ]
    for name, module_path, func_name in plugins:
        if name in TOOL_REGISTRY:
            continue
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            definition = getattr(mod, "TOOL_DEFINITION", {})
        except Exception as e:
            print(f"[plugins] failed to load {name}: {e}")
            continue
        TOOL_REGISTRY[name] = {
            "fn": fn,
            "description": definition.get("description", ""),
            "parameters": definition.get("parameters", {}),
            "meta": _meta(
                int(definition.get("tier", 3)),
                bool(definition.get("requires_approval", False)),
            ),
        }


def get_tool_names() -> list[str]:
    _register_plugin_tools()
    return sorted(TOOL_REGISTRY.keys())


def call_tool(name: str, **kwargs: Any) -> str:
    _register_plugin_tools()
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
    f"- {name}: {info['description']}" for name, info in sorted(TOOL_REGISTRY.items())
)
