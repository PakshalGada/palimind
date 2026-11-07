from __future__ import annotations

import contextvars
import inspect
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

# ── per-run context (set by the orchestrator) ────────────────────────────
#
# The authoritative context lives in a ContextVar so parallel agents cannot
# read or overwrite each other's workspace. ``_tool_context`` remains as a
# process-wide mirror for backwards compatibility with older tools/tests, but
# every code path that *executes* a tool reads the ContextVar.
_DEFAULT_TOOL_CONTEXT: dict[str, Any] = {
    "root": None,
    "extra_roots": [],
    "ollama_url": "",
    "chat_model": "",
    "light_model": "",
    "source_collector": None,
    "delegate_depth": 0,
    "agent_id": "",
    "session_id": "",
    "run_id": "",
    "write_access": False,
    "desktop_access": False,
    "desktop_control": False,
    "desktop_allowed_apps": [],
    "allow_network": False,
    "team_id": "",
    "team_run_id": "",
    "channel_id": "",
    "task_id": "",
    "team_emit": None,
    "team_loop": None,
}
_tool_context_var: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "palimind_tool_context", default=None
)


class _ContextMirror(dict):
    """Legacy process-wide view that also updates the current context.

    Kept so older tools/tests that write ``_tool_context[...]`` still affect
    execution, while concurrent workers continue to use their own ContextVar.
    """

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        ctx = _tool_context_var.get()
        if ctx is not None:
            updated = dict(ctx)
            updated[key] = value
            _tool_context_var.set(updated)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().update(*args, **kwargs)
        ctx = _tool_context_var.get()
        if ctx is not None:
            updated = dict(ctx)
            updated.update(*args, **kwargs)
            _tool_context_var.set(updated)


_tool_context: dict[str, Any] = _ContextMirror(_DEFAULT_TOOL_CONTEXT)
_context_lock = threading.Lock()


def make_tool_context(
    root: Path | None,
    ollama_url: str = "",
    chat_model: str = "",
    light_model: str = "",
    extra_roots: list[Path] | None = None,
    source_collector: list[dict] | None = None,
    *,
    read_only_roots: list[Path] | None = None,
    agent_id: str = "",
    session_id: str = "",
    run_id: str = "",
    write_access: bool = False,
    desktop_access: bool = False,
    desktop_control: bool = False,
    desktop_allowed_apps: list[str] | None = None,
    allow_network: bool = False,
    delegate_depth: int = 0,
    team_id: str = "",
    team_run_id: str = "",
    channel_id: str = "",
    task_id: str = "",
    team_emit: Any = None,
    team_loop: Any = None,
) -> dict[str, Any]:
    """Build a complete, isolated tool context."""
    return {
        "root": root,
        "extra_roots": list(extra_roots or []),
        "read_only_roots": list(read_only_roots or []),
        "ollama_url": ollama_url,
        "chat_model": chat_model,
        "light_model": light_model,
        # Optional sink for web sources discovered by tools, used by
        # deep research to build a citation-rich bibliography.
        "source_collector": source_collector,
        "delegate_depth": int(delegate_depth or 0),
        "agent_id": str(agent_id or ""),
        "session_id": str(session_id or ""),
        "run_id": str(run_id or ""),
        "write_access": bool(write_access),
        "desktop_access": bool(desktop_access),
        "desktop_control": bool(desktop_control),
        "desktop_allowed_apps": list(desktop_allowed_apps or []),
        "allow_network": bool(allow_network),
        "team_id": str(team_id or ""),
        "team_run_id": str(team_run_id or ""),
        "channel_id": str(channel_id or ""),
        "task_id": str(task_id or ""),
        "team_emit": team_emit,
        "team_loop": team_loop,
    }


def set_tool_context(
    root: Path | None,
    ollama_url: str = "",
    chat_model: str = "",
    light_model: str = "",
    extra_roots: list[Path] | None = None,
    source_collector: list[dict] | None = None,
    *,
    read_only_roots: list[Path] | None = None,
    agent_id: str = "",
    session_id: str = "",
    run_id: str = "",
    write_access: bool = False,
    desktop_access: bool = False,
    desktop_control: bool = False,
    desktop_allowed_apps: list[str] | None = None,
    allow_network: bool = False,
    delegate_depth: int = 0,
    team_id: str = "",
    team_run_id: str = "",
    channel_id: str = "",
    task_id: str = "",
    team_emit: Any = None,
    team_loop: Any = None,
) -> None:
    """Set the tool context for the current thread/task.

    Never share this implicitly between workers: call this once at the top of
    each worker (or pass ``tool_context=`` to :func:`run_agent`).
    """
    ctx = make_tool_context(
        root,
        ollama_url,
        chat_model,
        light_model,
        extra_roots,
        source_collector,
        read_only_roots=read_only_roots,
        agent_id=agent_id,
        session_id=session_id,
        run_id=run_id,
        write_access=write_access,
        desktop_access=desktop_access,
        desktop_control=desktop_control,
        desktop_allowed_apps=desktop_allowed_apps,
        allow_network=allow_network,
        delegate_depth=delegate_depth,
        team_id=team_id,
        team_run_id=team_run_id,
        channel_id=channel_id,
        task_id=task_id,
        team_emit=team_emit,
        team_loop=team_loop,
    )
    _tool_context_var.set(ctx)
    # Mirror for legacy readers. Execution never relies on this copy.
    with _context_lock:
        _tool_context.update(ctx)


def apply_tool_context(ctx: dict[str, Any]) -> None:
    """Install a fully-built context in the current thread/task."""
    merged = {**_DEFAULT_TOOL_CONTEXT, **ctx}
    _tool_context_var.set(merged)
    with _context_lock:
        _tool_context.update(merged)


def _get_context() -> dict[str, Any]:
    ctx = _tool_context_var.get()
    if ctx is not None:
        return dict(ctx)
    with _context_lock:
        return dict(_tool_context)


def _update_context(**changes: Any) -> None:
    """Atomically update the current context (used by delegate)."""
    ctx = _get_context()
    ctx.update(changes)
    _tool_context_var.set(ctx)
    with _context_lock:
        _tool_context.update(changes)


# ── per-call execution context (set/read by individual tools) ─────────────
# Distinct from the run context above: this carries short-lived flags a tool
# sets immediately before invoking a shared helper (e.g. browse-url requesting
# a screenshot). Guarded by its own lock so parallel agents cannot cross-talk.

_execution_context: dict[str, Any] = {"browse_screenshot": False}
_execution_lock = threading.Lock()


def set_execution_context(**kwargs: Any) -> None:
    with _execution_lock:
        _execution_context.update(kwargs)


def _get_execution_context() -> dict[str, Any]:
    with _execution_lock:
        return dict(_execution_context)


def _workspace_root() -> Path | None:
    return _get_context().get("root")


def _extra_roots() -> list[Path]:
    return list(_get_context().get("extra_roots") or [])


def _read_only_roots() -> list[Path]:
    return list(_get_context().get("read_only_roots") or [])


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


def _resolve_in_workspace(path: str, *, write: bool = False) -> Path | None:
    """Resolve *path* and confine it to the workspace root(s); None if outside.

    Extra knowledge roots are readable; writes are limited to the primary
    root (and any extra root not marked read-only).
    """
    primary = _workspace_root()
    extra = _extra_roots()
    readonly = _read_only_roots()
    roots = [r for r in [primary, *extra] if r is not None]
    if not roots:
        return Path(path).resolve()  # no workspace configured — legacy behaviour
    p = (roots[0] / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    inside: Path | None = None
    for root in roots:
        try:
            p.relative_to(root.resolve())
            inside = root.resolve()
            break
        except ValueError:
            continue
    if inside is None:
        return None
    if write and primary is not None and inside != primary.resolve():
        if any(inside == r.resolve() for r in readonly):
            return None
    return p


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


def _source_collector() -> list[dict] | None:
    return _get_context().get("source_collector")


def _record_web_sources(search_text: str) -> None:
    sink = _source_collector()
    if sink is None:
        return
    try:
        from palimind.generative.citation import parse_web_sources

        for source in parse_web_sources(search_text):
            sink.append(
                {
                    "url": source.url,
                    "title": source.title,
                    "snippet": source.snippet,
                    "content": source.content,
                }
            )
    except Exception:
        pass


def web_search(query: str, max_results: int = 4) -> str:
    from palimind.core.web_search import perform_web_search

    result = perform_web_search(query, max_results=max_results)
    _record_web_sources(result)
    return result


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a specific URL and return its extracted readable content."""
    from palimind.core.web_search import fetch_url_content

    content = fetch_url_content(url, max_chars=max_chars)
    sink = _source_collector()
    if sink is not None:
        sink.append({"url": url, "title": url, "snippet": "", "content": content[:2000]})
    return content


def x_search(query: str, max_results: int = 8) -> str:
    """Search X/Twitter for real-time social sentiment and trends."""
    from palimind.agents.tools.x_search import format_x_report
    from palimind.agents.tools.x_search import x_search as _x_search

    result = _x_search(query, max_results=max_results)
    sink = _source_collector()
    if sink is not None:
        for post in result.get("posts", []):
            sink.append(
                {
                    "url": post.get("url", ""),
                    "title": f"@{post.get('author') or 'x'}",
                    "snippet": (post.get("text") or "")[:400],
                    "content": "",
                }
            )
    return format_x_report(result)


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
    embed_model = config.get("embed_model", "bge-m3")
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
            rerank_enabled=bool(config.get("rerank", False)),
            rerank_model=config.get("rerank_model") or "cross-encoder/ms-marco-MiniLM-L-6-v2",
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
    sink = _source_collector()
    if sink is not None:
        for r in results:
            fp = str(r.get("file_path") or "")
            if not fp:
                continue
            sec = str(r.get("section_title") or r.get("main_section") or "")
            sink.append(
                {
                    "url": "",
                    "file": fp,
                    "section": sec,
                    "title": sec or fp.split("/")[-1],
                    "snippet": str(r.get("content") or "")[:600],
                    "content": str(r.get("content") or "")[:2000],
                }
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
        embed_model = config.get("embed_model", "bge-m3")

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


def remember(content: str, entry_type: str = "fact", confidence: float = 1.0) -> str:
    """Store a durable fact/preference in this agent's memory."""
    agent_id = str(_get_context().get("agent_id") or "")
    if not agent_id:
        return "Error: no active agent is associated with this run."
    try:
        from palimind.agents.memory import append_memory

        entry = append_memory(
            agent_id,
            str(entry_type or "fact"),
            str(content or ""),
            confidence=float(confidence or 1.0),
        )
    except Exception as exc:  # noqa: BLE001
        return f"Memory write error: {exc}"
    if entry is None:
        return "Error: this agent has no writable memory store (memory is off)."
    return f"Remembered [{entry['type']}] {entry['content']} (id={entry['id']})"


def forget(entry_id: str) -> str:
    """Delete a memory entry by id from this agent's memory."""
    agent_id = str(_get_context().get("agent_id") or "")
    if not agent_id:
        return "Error: no active agent is associated with this run."
    if not str(entry_id or "").strip():
        return "Error: entry_id is required"
    from palimind.agents.memory import delete_memory_entry_by_id

    ok = delete_memory_entry_by_id(agent_id, str(entry_id).strip())
    return "Forgotten." if ok else "Error: memory entry not found."


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
    p = _resolve_in_workspace(path, write=True)
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
    p = _resolve_in_workspace(path, write=True)
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
    """Execute Python code in an OS-sandboxed subprocess.

    This delegates to the same hardened implementation as the
    ``python-exec`` tool: bubblewrap isolation (no network, read-only
    workspace unless write access), address-space/CPU/file-size limits, and a
    hard timeout. Prints/stdout are captured and returned.
    """
    from palimind.security.sandbox import run_python_isolated
    from palimind.settings import PYTHON_EXEC_TIMEOUT

    ctx = _get_context()
    root = ctx.get("root")
    if root is None:
        return "Error: no active workspace configured for Python execution."
    # The model-supplied timeout may shorten, never extend, the hard ceiling.
    try:
        requested = int(timeout or PYTHON_EXEC_TIMEOUT)
    except (TypeError, ValueError):
        requested = PYTHON_EXEC_TIMEOUT
    effective = max(1, min(requested, PYTHON_EXEC_TIMEOUT))
    return run_python_isolated(
        code,
        root=Path(root),
        timeout_s=effective,
        allow_network=bool(ctx.get("allow_network", False)),
        allow_write=bool(ctx.get("write_access", False)),
    )


# ── summarization tool ────────────────────────────────────────────────────


def tool_search(query: str, limit: int = 8) -> str:
    """Discover tools by describing what you need.

    The agent only sees a routed subset of tool schemas. This meta-tool lets it
    search the full catalog when the routed set is missing a capability.
    """
    from palimind.agents.tool_router import select_tools
    from palimind.agents.tools.base import parameters_to_schema

    try:
        cap = max(1, min(int(limit or 8), 25))
    except (TypeError, ValueError):
        cap = 8
    names = select_tools(
        query,
        list(TOOL_REGISTRY),
        TOOL_REGISTRY,
        top_k=cap,
        include_core=False,
    )
    items = []
    for name in names:
        info = TOOL_REGISTRY.get(name) or {}
        meta = info.get("meta") or {}
        items.append(
            {
                "name": name,
                "description": info.get("description", ""),
                "tier": int(meta.get("tier", 3)),
                "requires_approval": bool(meta.get("requires_approval", True)),
                "parameters": parameters_to_schema(info.get("parameters") or {}),
            }
        )
    return json.dumps(items, indent=2, ensure_ascii=False)


# ── run checklist (todo) ─────────────────────────────────────────────────
#
# Multi-step work goes better when the model externalises its plan and marks
# items off as it goes. The list lives in the per-run tool context, so
# parallel agents never see each other's checklists.

_TODO_STATUSES = {"pending", "in_progress", "completed"}
_TODO_ALIASES = {
    "todo": "pending",
    "open": "pending",
    "not_started": "pending",
    "doing": "in_progress",
    "active": "in_progress",
    "running": "in_progress",
    "in-progress": "in_progress",
    "done": "completed",
    "complete": "completed",
    "finished": "completed",
}


def _normalize_todos(items: Any) -> list[dict[str, str]]:
    """Accept the shapes local models tend to emit and return a clean list."""
    if items is None:
        return []
    if isinstance(items, str):
        text = items.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, dict)):
                return _normalize_todos(parsed)
        except (TypeError, ValueError):
            pass
        # A newline/;-separated list is a common fallback.
        parts = [p.strip(" -•\t") for p in re.split(r"[\n;]+", text) if p.strip()]
        return [{"id": str(i + 1), "label": p[:500], "status": "pending"} for i, p in enumerate(parts)]
    if isinstance(items, dict):
        items = items.get("items") or items.get("todos") or [items]
    if not isinstance(items, (list, tuple)):
        return []

    out: list[dict[str, str]] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            label, status = item, "pending"
        elif isinstance(item, dict):
            label = str(
                item.get("label")
                or item.get("title")
                or item.get("text")
                or item.get("task")
                or ""
            )
            status = str(item.get("status") or "pending").strip().lower()
            status = _TODO_ALIASES.get(status, status)
        else:
            continue
        label = " ".join(label.split())[:500]
        if not label:
            continue
        if status not in _TODO_STATUSES:
            status = "pending"
        out.append({"id": str(index + 1), "label": label, "status": status})
    return out[:50]


def _format_todos(items: list[dict[str, str]]) -> str:
    if not items:
        return "Todo list cleared."
    done = sum(1 for item in items if item["status"] == "completed")
    marks = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
    lines = [f"Todo list — {done}/{len(items)} completed"]
    for item in items:
        lines.append(f"{marks[item['status']]} {item['id']}. {item['label']}")
    lines.append("Next: mark an item in_progress before starting it and completed when done.")
    return "\n".join(lines)


# Checklists are keyed by run so parallel agents never share a list. Tool
# execution happens on a sandbox thread whose context mirrors the run id.
_todo_store: dict[str, list[dict[str, str]]] = {}
_todo_stats: dict[str, dict[str, int]] = {}
_todo_lock = threading.Lock()
_TODO_STORE_LIMIT = 200
# Local models can spend an entire step budget rewriting the checklist. After
# this many updates only calls that reduce the number of open items (or clear
# the list) are accepted.
_TODO_UPDATE_LIMIT = 4


def _todo_key() -> str:
    ctx = _get_context()
    run_id = str(ctx.get("run_id") or "")
    if run_id:
        return run_id
    parts = (ctx.get("agent_id"), ctx.get("session_id"))
    key = "|".join(str(part or "") for part in parts)
    return key if key.strip("|") else "default"


def todo_write(items: Any = None, note: str = "") -> str:
    """Create or replace this run's task checklist.

    The checklist is surfaced to the UI as a live progress list. Send the
    *whole* list each call; this replaces the previous one so statuses stay
    authoritative.
    """
    normalized = _normalize_todos(items)
    key = _todo_key()
    open_items = sum(1 for item in normalized if item["status"] != "completed")
    with _todo_lock:
        stats = _todo_stats.get(key, {"updates": 0, "open": open_items})
        if stats["updates"] >= _TODO_UPDATE_LIMIT and open_items >= stats["open"]:
            return (
                "Checklist update limit reached. Stop rewriting the checklist; "
                "execute the next item with a real work tool, or complete the "
                "remaining items (a call that reduces open items is still accepted)."
            )
        _todo_store[key] = normalized
        _todo_stats[key] = {"updates": stats["updates"] + 1, "open": open_items}
        if len(_todo_store) > _TODO_STORE_LIMIT:
            for stale in list(_todo_store)[: len(_todo_store) - _TODO_STORE_LIMIT]:
                _todo_store.pop(stale, None)
    text = _format_todos(normalized)
    if note and str(note).strip():
        text += f"\nNote: {str(note).strip()[:500]}"
    return text


def get_todo_items() -> list[dict[str, str]]:
    """Return the current run's checklist (used by the agent event bridge)."""
    with _todo_lock:
        return list(_todo_store.get(_todo_key()) or [])


def clear_todo(run_id: str = "") -> None:
    """Drop a finished run's checklist.

    With no *run_id* this clears the whole in-memory store. Production callers
    always pass the run id; the no-argument form is for tests and bulk cleanup.
    """
    with _todo_lock:
        if not run_id:
            _todo_store.clear()
            _todo_stats.clear()
        else:
            _todo_store.pop(run_id, None)
            _todo_stats.pop(run_id, None)


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


# ── delegation tool ───────────────────────────────────────────────────────


def delegate(task: str, max_iterations: int = 6) -> str:
    """Run a focused, read-only sub-agent on a self-contained task.

    Lets an agent fan work out to a child without losing its own thread. The
    child gets the safe (read/network) tool set only and cannot delegate
    further, so recursion is bounded to a single level.
    """
    ctx = _get_context()
    depth = int(ctx.get("delegate_depth", 0) or 0)
    if depth >= 1:
        return "Error: delegate depth limit reached — sub-agents cannot delegate further."
    if not task or not str(task).strip():
        return "Error: task is required"

    ollama_url = ctx.get("ollama_url") or ""
    model = ctx.get("chat_model") or ctx.get("light_model") or ""
    if not ollama_url or not model:
        return "Error: delegation unavailable (no model/url configured)."

    from palimind.llm.mixture_of_expert.agents import run_agent as _run_agent

    sub_task: dict[str, Any] = {
        "agent_id": 901,
        "label": "Delegated sub-agent",
        "task": str(task),
        "tools": [
            "web_search",
            "fetch_url",
            "document_search",
            "memory_search",
            "read_file",
            "list_files",
            "glob_files",
            "grep_files",
            "summarize",
        ],
        "context": "",
    }

    _update_context(delegate_depth=depth + 1)
    try:
        output = _run_agent(
            901,
            sub_task,
            model,
            ollama_url,
            max_tool_iterations=max(1, int(max_iterations)),
        )
    except Exception as e:  # noqa: BLE001 - a failed child must not kill the parent
        return f"Error: delegated run failed: {e}"
    finally:
        _update_context(delegate_depth=depth)
    return output or "[delegated sub-agent produced no output]"


# ── registry ──────────────────────────────────────────────────────────────


def _meta(tier: int, requires_approval: bool) -> dict[str, Any]:
    return {"tier": tier, "requires_approval": requires_approval}


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    enum: tuple[str, ...] = (),
    default: Any = None,
    items: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Small helper for readable typed parameter declarations."""
    spec: dict[str, Any] = {"type": type, "description": description, "required": required}
    if enum:
        spec["enum"] = list(enum)
    if default is not None:
        spec["default"] = default
        spec["required"] = False
    if items:
        spec["items"] = items
    return spec


TOOL_REGISTRY: dict[str, dict] = {
    "tool_search": {
        "fn": tool_search,
        "description": (
            "Discover tools by describing the capability you need. Use this when "
            "the currently visible tool list does not contain the right tool."
        ),
        "parameters": {
            "query": _p(description="What you need to do, e.g. 'run tests' or 'read a PDF'"),
            "limit": _p(
                type="integer", description="Maximum tools to return (default 8)", default=8
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "todo_write": {
        "fn": todo_write,
        "description": (
            "Create or update a short task checklist for multi-step work. "
            "Send the full list each time; mark items pending, in_progress or "
            "completed so progress is visible and nothing is forgotten."
        ),
        "parameters": {
            "items": _p(
                type="array",
                description=(
                    "The complete checklist. Each item is an object like "
                    '{"label": "Find sources", "status": "completed"} '
                    "(status: pending | in_progress | completed)."
                ),
                items={
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["label"],
                },
            ),
            "note": _p(
                description="Optional short note about what changed",
                required=False,
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": False,
        "idempotent": True,
    },
    "web_search": {
        "fn": web_search,
        "description": "Search the web using DuckDuckGo and fetch page content for top results.",
        "parameters": {
            "query": _p(description="The search query string"),
            "max_results": _p(
                type="integer", description="Maximum number of results (default 4)", default=4
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "fetch_url": {
        "fn": fetch_url,
        "description": "Fetch a specific URL and extract its readable page content.",
        "parameters": {
            "url": _p(description="The full URL to fetch (http/https)"),
            "max_chars": _p(
                type="integer",
                description="Maximum characters to return (default 4000)",
                default=4000,
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "x_search": {
        "fn": x_search,
        "description": (
            "Search X/Twitter for real-time social sentiment, trends and posts. "
            "Returns overall sentiment, trending hashtags/tickers and cited posts."
        ),
        "parameters": {
            "query": _p(description="The topic or query to search on X/Twitter"),
            "max_results": _p(
                type="integer", description="Maximum number of posts (default 8)", default=8
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "document_search": {
        "fn": document_search,
        "description": "Search the user's indexed workspace documents (semantic + keyword).",
        "parameters": {
            "query": _p(description="The search query"),
            "limit": _p(
                type="integer", description="Maximum chunks to return (default 6)", default=6
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "memory_search": {
        "fn": memory_search,
        "description": "Search past conversation memory for relevant episodes.",
        "parameters": {
            "query": _p(description="The search query"),
            "limit": _p(type="integer", description="Maximum episodes (default 3)", default=3),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "remember": {
        "fn": remember,
        "description": "Store a durable fact or preference in this agent's memory.",
        "parameters": {
            "content": _p(description="The fact/preference to remember"),
            "entry_type": _p(
                type="string",
                description="fact, preference, decision, entity, result or error",
                default="fact",
            ),
            "confidence": _p(
                type="number", description="Confidence 0..1 (default 1.0)", default=1.0
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": False,
        "idempotent": False,
    },
    "forget": {
        "fn": forget,
        "description": "Delete one memory entry by its id.",
        "parameters": {
            "entry_id": _p(description="Memory entry id"),
        },
        "meta": _meta(1, False),
        "parallel_safe": False,
        "idempotent": False,
    },
    "read_file": {
        "fn": read_file,
        "description": "Read a file from the workspace (sandboxed to the active field).",
        "parameters": {
            "path": _p(description="Absolute or workspace-relative path to the file"),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "write_file": {
        "fn": write_file,
        "description": "Write content to a file in the workspace (sandboxed to the active field).",
        "parameters": {
            "path": _p(description="Absolute or workspace-relative path to the file"),
            "content": _p(description="Text content to write"),
        },
        "meta": _meta(2, True),
        "parallel_safe": False,
        "idempotent": False,
    },
    "list_files": {
        "fn": list_files,
        "description": "List files and directories at a given workspace path.",
        "parameters": {
            "path": _p(description="Directory path (default '.')", default="."),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "glob_files": {
        "fn": glob_files,
        "description": "Recursively list workspace files matching a glob pattern (e.g. '**/*.py').",
        "parameters": {
            "pattern": _p(description="The glob pattern to match file paths"),
            "path": _p(description="Directory to search from (default '.')", default="."),
            "max_results": _p(type="integer", description="Max results (default 200)", default=200),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "grep_files": {
        "fn": grep_files,
        "description": "Search file contents inside the workspace for a pattern (case-insensitive regex).",
        "parameters": {
            "pattern": _p(description="Regex or plain-text pattern to search for"),
            "path": _p(description="Directory to search from (default '.')", default="."),
            "max_results": _p(type="integer", description="Max matches (default 50)", default=50),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "search_replace": {
        "fn": search_replace,
        "description": "Surgically replace occurrences of a string in a workspace file.",
        "parameters": {
            "path": _p(description="Absolute or workspace-relative path to the file"),
            "old_string": _p(description="Exact text to find"),
            "new_string": _p(description="Replacement text"),
            "count": _p(
                type="integer",
                description="Number of occurrences to replace (default 1)",
                default=1,
            ),
        },
        "meta": _meta(2, True),
        "parallel_safe": False,
        "idempotent": False,
    },
    "run_python": {
        "fn": run_python,
        "description": "Execute Python code in an isolated subprocess. stdout is returned.",
        "parameters": {
            "code": _p(description="Python code to execute"),
            "timeout": _p(
                type="integer", description="Timeout in seconds (default 15)", default=15
            ),
        },
        "meta": _meta(2, True),
        "parallel_safe": False,
        "idempotent": False,
    },
    "summarize": {
        "fn": summarize,
        "description": "Summarize long text using the light model.",
        "parameters": {
            "text": _p(description="The text to summarize"),
            "max_chars": _p(
                type="integer",
                description="Target length in characters (default 1000)",
                default=1000,
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": True,
        "idempotent": True,
    },
    "delegate": {
        "fn": delegate,
        "description": (
            "Delegate a self-contained research or analysis task to a focused "
            "read-only sub-agent and return its findings."
        ),
        "parameters": {
            "task": _p(description="A clear, self-contained task description for the sub-agent"),
            "max_iterations": _p(
                type="integer",
                description="Maximum tool steps for the sub-agent (default 6)",
                default=6,
            ),
        },
        "meta": _meta(1, False),
        "parallel_safe": False,
        "idempotent": False,
    },
}


# Folder-based tools registered into the live registry. Names are the public
# tool ids agents select; (module_path, function) maps to the manifest
# implementation. `python-exec` and `web-search` are intentionally omitted —
# their ids (`run_python`, `web_search`) already exist as core tools.
_PLUGIN_TOOLS: list[tuple[str, str, str]] = [
    ("run_shell", "palimind.agents.tools.shell-exec.tool", "run_shell"),
    ("csv_query", "palimind.agents.tools.csv-query.tool", "csv_query"),
    ("sqlite_query", "palimind.agents.tools.sqlite-query.tool", "sqlite_query"),
    ("query_graph", "palimind.agents.tools.knowledge-graph.tool", "query_graph"),
    ("browse_url", "palimind.agents.tools.browse-url.tool", "browse_url"),
    ("arxiv_search", "palimind.agents.tools.arxiv-search.tool", "arxiv_search"),
    ("fetch_rss", "palimind.agents.tools.rss-fetch.tool", "fetch_rss"),
    ("mqtt", "palimind.agents.tools.mqtt.tool", "mqtt"),
    ("image_generate", "palimind.agents.tools.image-generate.tool", "image_generate"),
]

# Plugins that expose several tools from one module via a module-level `TOOLS`
# mapping (name -> {fn, description, parameters, tier, requires_approval, ...}).
_MULTI_TOOL_PLUGINS: list[str] = [
    "palimind.agents.tools.browser.tool",
    "palimind.agents.tools.desktop.tool",
    "palimind.agents.tools.research.tool",
    "palimind.agents.tools.git.tool",
    "palimind.agents.tools.apply-patch.tool",
    "palimind.agents.tools.office.tool",
    "palimind.agents.tools.data.tool",
    "palimind.agents.task_tools",
    "palimind.agents.channel_tools",
    "palimind.agents.wait_tools",
    "palimind.agents.flow_tools",
    "palimind.agents.routine_tools",
    "palimind.agents.mcp_tools",
    "palimind.agents.secrets_tools",
    "palimind.agents.visual_tools",
    "palimind.agents.browser_profile_tools",
]

# Names of drop-in user tools currently merged into TOOL_REGISTRY. Tracked so a
# deleted user tool disappears on the next reload instead of lingering.
_user_tool_names: set[str] = set()
_user_tools_loaded = False
_mcp_tools_loaded = False


def _user_tool_fn(tool: Any) -> Any:
    """Adapt an async :class:`Tool` to the sync callable TOOL_REGISTRY expects."""

    def _run(**kwargs: Any) -> str:
        import asyncio

        from palimind.agents.tools.base import ToolContext

        ctx = ToolContext(
            workspace_root=_workspace_root(),
            allowed_paths=list(_extra_roots()),
            settings={},
        )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(tool.run(ctx, **kwargs))
        else:
            # A loop is already running in this thread (rare for call_tool, but
            # tests and embedders may do this): use a private loop.
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(tool.run(ctx, **kwargs))
            finally:
                loop.close()
        return str(result)

    return _run


def _register_user_tools(*, force: bool = False) -> None:
    """Merge drop-in tools from ~/.palimind/tools into the live registry."""
    global _user_tools_loaded
    if _user_tools_loaded and not force:
        return
    from palimind.agents.tools.registry import discover_user_tools
    from palimind.settings import TOOL_TIMEOUT_S

    current = discover_user_tools()
    for old in _user_tool_names - set(current):
        TOOL_REGISTRY.pop(old, None)
    for name, tool in current.items():
        # Built-ins always win; only replace a previous user tool.
        if name in TOOL_REGISTRY and name not in _user_tool_names:
            continue
        TOOL_REGISTRY[name] = {
            "fn": _user_tool_fn(tool),
            "description": tool.description,
            "parameters": dict(tool.parameters or {}),
            "meta": _meta(tool.tier, tool.requires_approval),
            "timeout_s": int(tool.timeout_s or TOOL_TIMEOUT_S),
            "parallel_safe": bool(tool.parallel_safe),
            "idempotent": bool(tool.idempotent),
            "source": tool.source,
        }
    _user_tool_names.clear()
    _user_tool_names.update(current)
    _user_tools_loaded = True


def _register_mcp_tools(*, force: bool = False) -> None:
    """Merge tools from trusted local MCP servers into the live registry."""
    global _mcp_tools_loaded
    if _mcp_tools_loaded and not force:
        return
    from palimind.agents.mcp import get_manager
    from palimind.settings import MCP_ENABLE

    if not MCP_ENABLE:
        _mcp_tools_loaded = True
        return
    manager = get_manager()
    if manager.configs:
        manager.register_into(TOOL_REGISTRY)
    _mcp_tools_loaded = True


def _register_plugin_tools(*, force: bool = False) -> None:
    """Lazily merge every folder-based tool into the live registry so the UI
    and the agent loop can see and call them. Idempotent and best-effort: one
    unloadable plugin must never break the rest.

    ``force=True`` re-scans drop-in user tools and MCP servers (used by the
    reload endpoints); the normal path is cached.
    """
    import importlib

    from palimind.settings import TOOL_TIMEOUT_S

    for name, module_path, func_name in _PLUGIN_TOOLS:
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
            "timeout_s": int(definition.get("timeout_s") or TOOL_TIMEOUT_S),
            "parallel_safe": bool(definition.get("parallel_safe", False)),
            "idempotent": bool(definition.get("idempotent", False)),
        }

    for module_path in _MULTI_TOOL_PLUGINS:
        try:
            mod = importlib.import_module(module_path)
            module_tools = getattr(mod, "TOOLS", {})
        except Exception as e:
            print(f"[plugins] failed to load multi-tool module {module_path}: {e}")
            continue
        for name, spec in module_tools.items():
            if name in TOOL_REGISTRY:
                continue
            TOOL_REGISTRY[name] = {
                "fn": spec["fn"],
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters", {}),
                "meta": _meta(
                    int(spec.get("tier", 3)),
                    bool(spec.get("requires_approval", False)),
                ),
                "timeout_s": int(spec.get("timeout_s") or TOOL_TIMEOUT_S),
            }

    try:
        from palimind.agents.team_tools import register_team_tools

        register_team_tools()
    except Exception as e:
        print(f"[plugins] failed to load team tools: {e}")

    try:
        _register_user_tools(force=force)
    except Exception as e:
        print(f"[plugins] failed to load user tools: {e}")

    try:
        _register_mcp_tools(force=force)
    except Exception as e:
        print(f"[plugins] failed to load MCP tools: {e}")


def get_tool_names() -> list[str]:
    _register_plugin_tools()
    return sorted(TOOL_REGISTRY.keys())


def call_tool(name: str, /, **kwargs: Any) -> str:
    """Execute a registered tool under the sandbox (timeout, output clamp and
    audit), returning a string. Never raises — errors come back as text so the
    agent loop can feed them back to the model."""
    _register_plugin_tools()
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"Error: unknown tool '{name}'. Available: {', '.join(get_tool_names())}"
    fn = entry["fn"]
    ctx = _get_context()
    agent_id = str(ctx.get("agent_id") or "")
    session_id = str(ctx.get("session_id") or "")

    # Validate/coerce arguments against the tool's declared schema first. This
    # turns the common model mistake of sending "5" for an integer into a
    # corrected call instead of a confusing failure deep inside the tool.
    from palimind.agents.tools.base import coerce_tool_args

    kwargs, arg_error = coerce_tool_args(name, entry.get("parameters"), kwargs)
    if arg_error:
        return arg_error

    # Surface remaining bad arguments as an argument error (the loop
    # retries/adjusts), rather than a tool crash. Non-introspectable callables
    # are let through.
    try:
        inspect.signature(fn).bind(**kwargs)
    except TypeError as e:
        return f"Tool '{name}' argument error: {e}"
    except (ValueError, AttributeError):
        pass

    from palimind.agents.tools.sandbox import run_sandboxed_sync
    from palimind.settings import TOOL_TIMEOUT_S

    timeout_s = int(entry.get("timeout_s") or TOOL_TIMEOUT_S)
    started = time.perf_counter()
    try:
        output = run_sandboxed_sync(
            lambda: fn(**kwargs),
            timeout_s=timeout_s,
            tool_name=name,
            args_summary=kwargs,
            agent_id=agent_id,
            session_id=session_id,
        )
        ok = not str(output).startswith(("Error", "Access denied", "Tool '"))
        try:
            from palimind import metrics

            metrics.record_tool(name, ok, (time.perf_counter() - started) * 1000.0)
        except Exception:
            pass
        return output
    except Exception as e:  # noqa: BLE001 - tools must never crash the loop
        try:
            from palimind import metrics

            metrics.record_tool(name, False, (time.perf_counter() - started) * 1000.0)
        except Exception:
            pass
        return f"Tool '{name}' error: {e}"


AVAILABLE_TOOLS_DESC = "\n".join(
    f"- {name}: {info['description']}" for name, info in sorted(TOOL_REGISTRY.items())
)
