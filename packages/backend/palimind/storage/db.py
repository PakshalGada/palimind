from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from palimind.config import db_path

# Serializes full reindex / graph builds so two can never run concurrently
# against the same field's SQLite + vector store (thread-safety + CPU guard).
INDEX_WRITE_LOCK = threading.Lock()


def init_db(root: Path) -> None:
    conn = sqlite3.connect(db_path(root), timeout=30.0)
    try:
        cur = conn.cursor()

        # Enable WAL mode for concurrent reads and faster writes.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys = ON")

        cur.execute("PRAGMA table_info(files)")
        columns = [col[1] for col in cur.fetchall()]
        if columns and "path" not in columns:
            cur.execute("DROP TABLE IF EXISTS chunks")
            cur.execute("DROP TABLE IF EXISTS summaries_fts")
            cur.execute("DROP TABLE IF EXISTS files")

        # Drop removed tables from older index versions
        cur.execute("DROP TABLE IF EXISTS financial_facts")
        cur.execute("DROP TABLE IF EXISTS timeline_events")

        # ── files ─────────────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                path            TEXT UNIQUE NOT NULL,
                md5_hash        TEXT,
                last_indexed    REAL,
                summary         TEXT DEFAULT '',
                doc_year        INTEGER,
                doc_type        TEXT DEFAULT 'other',
                entity_name     TEXT DEFAULT '',
                total_pages     INTEGER,
                language        TEXT DEFAULT 'en'
            )
        """)

        # ── chunks ────────────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id         INTEGER NOT NULL,
                chunk_index     INTEGER NOT NULL,
                chunk_type      TEXT NOT NULL,
                content         TEXT NOT NULL,
                section_title   TEXT DEFAULT '',
                subsection      TEXT DEFAULT '',
                parent_section  TEXT DEFAULT '',
                main_section    TEXT DEFAULT '',
                page_number     INTEGER,
                word_count      INTEGER,
                token_estimate  INTEGER,
                embed_text      TEXT DEFAULT '',
                media_start_ts  REAL,
                media_end_ts    REAL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)

        # ── FTS5 on chunks.content ────────────────────────────────────────────
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'")
        has_fts = cur.fetchone() is not None

        if not has_fts:
            cur.execute("""
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    content,
                    content='chunks',
                    content_rowid='id'
                )
            """)
            cur.execute("""
                CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            cur.execute("""
                CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
                END;
            """)
            cur.execute("""
                CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
                    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
                END;
            """)
            cur.execute("INSERT INTO chunks_fts(rowid, content) SELECT id, content FROM chunks")

        # ── FTS5 on files.summary (document-level retrieval) ───────────────
        # Lets "which report covers X?" match a whole-document summary even
        # when no individual chunk contains the phrasing.
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='summaries_fts'")
        has_summary_fts = cur.fetchone() is not None

        if not has_summary_fts:
            cur.execute("""
                CREATE VIRTUAL TABLE summaries_fts USING fts5(
                    summary,
                    content='files',
                    content_rowid='id'
                )
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_ai AFTER INSERT ON files BEGIN
                    INSERT INTO summaries_fts(rowid, summary) VALUES (new.id, new.summary);
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_ad AFTER DELETE ON files BEGIN
                    INSERT INTO summaries_fts(summaries_fts, rowid, summary)
                    VALUES('delete', old.id, old.summary);
                END;
            """)
            cur.execute("""
                CREATE TRIGGER IF NOT EXISTS files_fts_au AFTER UPDATE ON files BEGIN
                    INSERT INTO summaries_fts(summaries_fts, rowid, summary)
                    VALUES('delete', old.id, old.summary);
                    INSERT INTO summaries_fts(rowid, summary) VALUES (new.id, new.summary);
                END;
            """)
            cur.execute("INSERT INTO summaries_fts(rowid, summary) SELECT id, summary FROM files")

        # ── Backward-compatible migrations ────────────────────────────────────
        cur.execute("PRAGMA table_info(files)")

        file_cols = {col[1] for col in cur.fetchall()}
        for col_def in [
            ("summary", "TEXT DEFAULT ''"),
            ("doc_year", "INTEGER"),
            ("doc_type", "TEXT DEFAULT 'other'"),
            ("entity_name", "TEXT DEFAULT ''"),
            ("total_pages", "INTEGER"),
            ("language", "TEXT DEFAULT 'en'"),
            ("source_id", "TEXT DEFAULT ''"),
            ("source_kind", "TEXT DEFAULT ''"),
            ("source_url", "TEXT DEFAULT ''"),
            ("source_title", "TEXT DEFAULT ''"),
            ("source_site", "TEXT DEFAULT ''"),
            ("source_author", "TEXT DEFAULT ''"),
            ("source_published_at", "TEXT DEFAULT ''"),
            ("source_fetched_at", "REAL"),
        ]:
            col_name, col_type = col_def
            if col_name not in file_cols:
                cur.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")

        cur.execute("PRAGMA table_info(chunks)")
        chunk_cols = {col[1] for col in cur.fetchall()}
        for col_def in [
            ("section_title", "TEXT DEFAULT ''"),
            ("subsection", "TEXT DEFAULT ''"),
            ("parent_section", "TEXT DEFAULT ''"),
            ("main_section", "TEXT DEFAULT ''"),
            ("page_number", "INTEGER"),
            ("word_count", "INTEGER"),
            ("token_estimate", "INTEGER"),
            ("embed_text", "TEXT DEFAULT ''"),
            ("media_start_ts", "REAL"),
            ("media_end_ts", "REAL"),
        ]:
            col_name, col_type = col_def
            if col_name not in chunk_cols:
                cur.execute(f"ALTER TABLE chunks ADD COLUMN {col_name} {col_type}")

        # ── entity_mentions ───────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entity_mentions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id    INTEGER NOT NULL,
                entity_text TEXT NOT NULL,
                entity_type TEXT DEFAULT '',
                context     TEXT DEFAULT '',
                FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_mentions
            ON entity_mentions(entity_text, entity_type)
        """)

        # ── knowledge sources ─────────────────────────────────────────────────
        # One row per saved web page / note / file. ``file_path`` points at the
        # Markdown file in the index, so retrieval and graph stay source-agnostic.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id                TEXT PRIMARY KEY,
                kind              TEXT NOT NULL DEFAULT 'web',
                url               TEXT DEFAULT '',
                canonical_url     TEXT DEFAULT '',
                title             TEXT DEFAULT '',
                author            TEXT DEFAULT '',
                site              TEXT DEFAULT '',
                published_at      TEXT DEFAULT '',
                fetched_at        REAL,
                etag              TEXT DEFAULT '',
                last_modified     TEXT DEFAULT '',
                content_hash      TEXT DEFAULT '',
                file_path         TEXT DEFAULT '',
                snapshot_path     TEXT DEFAULT '',
                status            TEXT NOT NULL DEFAULT 'queued',
                error             TEXT DEFAULT '',
                note              TEXT DEFAULT '',
                tags              TEXT DEFAULT '[]',
                reading_state     TEXT DEFAULT 'unread',
                favorite          INTEGER DEFAULT 0,
                refresh_interval  INTEGER DEFAULT 0,
                last_checked      REAL,
                parent_id         TEXT DEFAULT '',
                change_summary    TEXT DEFAULT '',
                created_at        REAL,
                updated_at        REAL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_file ON sources(file_path)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_canonical ON sources(canonical_url)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status)"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at  REAL,
                updated_at  REAL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS source_collections (
                source_id     TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                PRIMARY KEY (source_id, collection_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS capture_profiles (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                domain      TEXT NOT NULL,
                headers     TEXT DEFAULT '{}',
                cookies     TEXT DEFAULT '',
                user_agent  TEXT DEFAULT '',
                created_at  REAL,
                updated_at  REAL
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_capture_profiles_domain "
            "ON capture_profiles(domain)"
        )
        cur.execute("PRAGMA table_info(sources)")
        source_cols = {col[1] for col in cur.fetchall()}
        for col_def in [
            ("parent_id", "TEXT DEFAULT ''"),
            ("change_summary", "TEXT DEFAULT ''"),
        ]:
            col_name, col_type = col_def
            if col_name not in source_cols:
                cur.execute(f"ALTER TABLE sources ADD COLUMN {col_name} {col_type}")

        # ── incremental index runs ───────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS index_files (
                run_id      TEXT NOT NULL,
                path        TEXT NOT NULL,
                md5         TEXT DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'queued',
                error       TEXT DEFAULT '',
                attempts    INTEGER NOT NULL DEFAULT 0,
                updated_at  REAL,
                PRIMARY KEY (run_id, path)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_index_files_run
            ON index_files(run_id, status)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS index_events (
                run_id      TEXT NOT NULL,
                seq         INTEGER NOT NULL,
                type        TEXT NOT NULL,
                payload     TEXT NOT NULL DEFAULT '{}',
                created_at  REAL NOT NULL,
                PRIMARY KEY (run_id, seq)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_index_events_run
            ON index_events(run_id, seq)
        """)

        conn.commit()
    finally:
        conn.close()


_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


def _ensure_schema(root: Path, conn: sqlite3.Connection) -> sqlite3.Connection:
    """Migrate an old index DB once per process before reading from it.

    Read paths (`fts_search`, graph queries) used to assume the newest columns
    existed. Against an index created by an older build, `c.main_section` made
    the whole FTS query raise and keyword search silently returned nothing —
    which looks exactly like "the document isn't there". Check cheaply and run
    the idempotent migrations once.
    """
    key = str(db_path(root))
    if key in _SCHEMA_READY:
        return conn
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return conn
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
            file_cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
            has_summary_fts = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='summaries_fts'"
                ).fetchone()
                is not None
            )
            has_sources = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sources'"
                ).fetchone()
                is not None
            )
            has_profiles = (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_profiles'"
                ).fetchone()
                is not None
            )
            source_cols = (
                {row[1] for row in conn.execute("PRAGMA table_info(sources)")}
                if has_sources
                else set()
            )
            if (
                "main_section" not in cols
                or "embed_text" not in cols
                or not has_summary_fts
                or not has_sources
                or not has_profiles
                or "source_id" not in file_cols
                or "change_summary" not in source_cols
            ):
                conn.close()
                init_db(root)
                conn = sqlite3.connect(db_path(root), timeout=30.0)
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            # A read must never fail because a best-effort migration failed.
            pass
        _SCHEMA_READY.add(key)
    return conn


def get_connection(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return _ensure_schema(root, conn)


# ── files ──────────────────────────────────────────────────────────────────────


def get_file_hash(conn: sqlite3.Connection, path: str) -> str | None:
    cur = conn.execute("SELECT md5_hash FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_file(
    conn: sqlite3.Connection,
    path: str,
    md5_hash: str,
    timestamp: float,
    *,
    doc_year: int | None = None,
    doc_type: str = "other",
    entity_name: str = "",
    source: dict | None = None,
) -> int:
    provenance = dict(source or {})
    if not provenance:
        # Web/notes sources are written into the index by the normal crawler;
        # pick up their provenance without threading it through every caller.
        try:
            row = conn.execute(
                """
                SELECT id, kind, url, title, site, author, published_at, fetched_at
                FROM sources WHERE file_path = ?
                """,
                (path,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            provenance = {
                "id": row[0],
                "kind": row[1],
                "url": row[2],
                "title": row[3],
                "site": row[4],
                "author": row[5],
                "published_at": row[6],
                "fetched_at": row[7],
            }
    if provenance.get("kind") == "web" and (not doc_type or doc_type == "other"):
        doc_type = "web"
    conn.execute(
        """
        INSERT INTO files (
            path, md5_hash, last_indexed, doc_year, doc_type, entity_name,
            source_id, source_kind, source_url, source_title, source_site,
            source_author, source_published_at, source_fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            md5_hash=excluded.md5_hash,
            last_indexed=excluded.last_indexed,
            doc_year=excluded.doc_year,
            doc_type=excluded.doc_type,
            entity_name=excluded.entity_name,
            source_id=excluded.source_id,
            source_kind=excluded.source_kind,
            source_url=excluded.source_url,
            source_title=excluded.source_title,
            source_site=excluded.source_site,
            source_author=excluded.source_author,
            source_published_at=excluded.source_published_at,
            source_fetched_at=excluded.source_fetched_at
        """,
        (
            path,
            md5_hash,
            timestamp,
            doc_year,
            doc_type,
            entity_name,
            str(provenance.get("id") or ""),
            str(provenance.get("kind") or ""),
            str(provenance.get("url") or ""),
            str(provenance.get("title") or ""),
            str(provenance.get("site") or ""),
            str(provenance.get("author") or ""),
            str(provenance.get("published_at") or ""),
            provenance.get("fetched_at"),
        ),
    )
    cur = conn.execute("SELECT id FROM files WHERE path = ?", (path,))
    return cur.fetchone()[0]


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def insert_chunks(
    conn: sqlite3.Connection,
    file_id: int,
    chunks_data: list,
) -> list[int]:
    """Insert chunks and return the list of newly assigned primary key IDs.

    Accepted tuple layouts (oldest first):
    * ``(chunk_index, chunk_type, content)``
    * ``(…, section_title, subsection, parent_section, page_number,
      word_count, token_estimate)``
    * ``(…, media_start_ts, media_end_ts)``
    * ``(…, media_start_ts, media_end_ts, embed_text)``
    * ``(…, media_start_ts, media_end_ts, embed_text, main_section)``

    Returns ``list[int]`` of inserted row IDs in the same order.
    """
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    chunk_ids: list[int] = []
    cur = conn.cursor()
    for row in chunks_data:
        idx, ctype, content = row[0], row[1], row[2]
        section_title = row[3] if len(row) > 3 else ""
        subsection = row[4] if len(row) > 4 else ""
        parent_section = row[5] if len(row) > 5 else ""
        page_number = row[6] if len(row) > 6 else None
        word_count = row[7] if len(row) > 7 else None
        token_estimate = row[8] if len(row) > 8 else None
        media_start_ts = row[9] if len(row) > 9 else None
        media_end_ts = row[10] if len(row) > 10 else None
        embed_text = row[11] if len(row) > 11 else ""
        main_section = row[12] if len(row) > 12 else ""
        cur.execute(
            """INSERT INTO chunks
               (file_id, chunk_index, chunk_type, content,
                section_title, subsection, parent_section, main_section,
                page_number, word_count, token_estimate, embed_text,
                media_start_ts, media_end_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id,
                idx,
                ctype,
                content,
                section_title or "",
                subsection or "",
                parent_section or "",
                main_section or "",
                page_number,
                word_count,
                token_estimate,
                embed_text or content,
                media_start_ts,
                media_end_ts,
            ),
        )
        if cur.lastrowid is not None:
            chunk_ids.append(int(cur.lastrowid))
    return chunk_ids


def upsert_file_summary(conn: sqlite3.Connection, path: str, summary: str) -> None:
    """Store (or overwrite) the generated summary for a file."""
    conn.execute(
        "UPDATE files SET summary = ? WHERE path = ?",
        (summary, path),
    )


def get_file_summary(conn: sqlite3.Connection, path: str) -> str | None:
    """Return the stored summary for *path*, or None if not found."""
    cur = conn.execute("SELECT summary FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    return row[0] if row else None


def get_all_files(conn: sqlite3.Connection) -> list[dict]:
    """Return a list of dicts with ``path``, ``summary``, ``doc_year``, ``doc_type`` for every indexed file."""
    cur = conn.execute(
        "SELECT path, summary, doc_year, doc_type, entity_name, "
        "source_url, source_title, source_site, source_fetched_at "
        "FROM files ORDER BY path"
    )
    return [
        {
            "path": row[0],
            "summary": row[1] or "",
            "doc_year": row[2],
            "doc_type": row[3] or "other",
            "entity_name": row[4] or "",
            "source_url": row[5] or "",
            "source_title": row[6] or "",
            "source_site": row[7] or "",
            "source_fetched_at": row[8],
        }
        for row in cur.fetchall()
    ]


def get_files_with_hash(conn: sqlite3.Connection) -> list[dict]:
    """Return every indexed file with its md5 hash (used for incremental graphs)."""
    cur = conn.execute(
        "SELECT path, md5_hash, summary, doc_year, doc_type, entity_name, "
        "source_url, source_title, source_site, source_fetched_at "
        "FROM files ORDER BY path"
    )
    return [
        {
            "path": row[0],
            "md5": row[1] or "",
            "summary": row[2] or "",
            "doc_year": row[3],
            "doc_type": row[4] or "other",
            "entity_name": row[5] or "",
            "source_url": row[6] or "",
            "source_title": row[7] or "",
            "source_site": row[8] or "",
            "source_fetched_at": row[9],
        }
        for row in cur.fetchall()
    ]


def get_chunk_ids_for_file(conn: sqlite3.Connection, path: str) -> list[tuple[int, str]]:
    """Return ``(chunk_id, content)`` pairs for a file, ordered by chunk_index."""
    cur = conn.execute(
        """
        SELECT c.id, c.content FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE f.path = ? ORDER BY c.chunk_index
        """,
        (path,),
    )
    return cur.fetchall()


def clear_entity_mentions_for_path(conn: sqlite3.Connection, path: str) -> None:
    conn.execute(
        """
        DELETE FROM entity_mentions WHERE chunk_id IN (
            SELECT c.id FROM chunks c JOIN files f ON c.file_id = f.id WHERE f.path = ?
        )
        """,
        (path,),
    )


def insert_entity_mentions(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO entity_mentions(chunk_id, entity_text, entity_type, context) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )


def get_chunks_for_file(conn: sqlite3.Connection, path: str) -> list[str]:
    """Return all chunk contents for a given file path, ordered by chunk_index."""
    cur = conn.execute(
        """
        SELECT c.content
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE f.path = ?
          AND c.chunk_type IN ('text', 'caption', 'transcript')
        ORDER BY c.chunk_index
        """,
        (path,),
    )
    return [row[0] for row in cur.fetchall()]


def get_rich_chunks_for_file(conn: sqlite3.Connection, path: str) -> list[dict]:
    """Return full chunk rows (including metadata) for a given file path."""
    cur = conn.execute(
        """
        SELECT c.id, c.chunk_index, c.chunk_type, c.content,
               c.section_title, c.subsection, c.parent_section, c.main_section,
               c.page_number, c.word_count, c.token_estimate,
               f.doc_year, f.doc_type, f.entity_name
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE f.path = ?
        ORDER BY c.chunk_index
        """,
        (path,),
    )
    return [
        {
            "chunk_db_id": row[0],
            "chunk_index": row[1],
            "chunk_type": row[2],
            "content": row[3],
            "section_title": row[4] or "",
            "subsection": row[5] or "",
            "parent_section": row[6] or "",
            "main_section": row[7] or "",
            "page_number": row[8],
            "word_count": row[9],
            "token_estimate": row[10],
            "file_path": path,
            "doc_year": row[11],
            "doc_type": row[12] or "other",
            "entity_name": row[13] or "",
        }
        for row in cur.fetchall()
    ]


def get_chunk_neighbors(
    conn: sqlite3.Connection,
    path: str,
    chunk_index: int,
    before: int = 1,
    after: int = 1,
) -> list[dict]:
    """Return chunks adjacent to (file_path, chunk_index), ordered by chunk_index."""
    cur = conn.execute(
        """
        SELECT c.id, c.chunk_index, c.chunk_type, c.content,
               c.section_title, f.doc_year, f.doc_type,
               c.media_start_ts, c.media_end_ts, c.page_number
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE f.path = ?
          AND c.chunk_index BETWEEN ? AND ?
          AND c.chunk_type IN ('text', 'caption', 'transcript')
        ORDER BY c.chunk_index
        """,
        (path, chunk_index - before, chunk_index + after),
    )
    return [
        {
            "chunk_db_id": row[0],
            "chunk_index": row[1],
            "chunk_type": row[2],
            "content": row[3],
            "section_title": row[4] or "",
            "file_path": path,
            "doc_year": row[5],
            "doc_type": row[6] or "other",
            "media_start_ts": row[7],
            "media_end_ts": row[8],
            "page_number": row[9],
        }
        for row in cur.fetchall()
    ]


def get_section_chunks(
    conn: sqlite3.Connection,
    path: str,
    parent_section: str,
    section_title: str,
    main_section: str = "",
) -> list[dict]:
    """Return every chunk of one section in a file, ordered by chunk_index.

    This is the "parent" side of small-to-big retrieval: children are matched
    individually, then their whole section is assembled for the LLM.
    """
    conditions = ["f.path = ?", "c.chunk_type IN ('text', 'table')"]
    params: list = [path]

    # Prefer the most specific identity available. Sections from different
    # top-level items can share a subsection title, so include main_section.
    if main_section:
        conditions.append("c.main_section = ?")
        params.append(main_section)
    if parent_section:
        conditions.append("c.parent_section = ?")
        params.append(parent_section)
    if section_title:
        conditions.append("c.section_title = ?")
        params.append(section_title)

    cur = conn.execute(
        f"""
        SELECT c.id, c.chunk_index, c.chunk_type, c.content,
               c.section_title, c.subsection, c.parent_section, c.main_section,
               c.page_number, c.word_count, c.token_estimate,
               f.doc_year, f.doc_type
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE {" AND ".join(conditions)}
        ORDER BY c.chunk_index
        """,
        params,
    )
    return [
        {
            "chunk_db_id": row[0],
            "chunk_index": row[1],
            "chunk_type": row[2],
            "content": row[3],
            "section_title": row[4] or "",
            "subsection": row[5] or "",
            "parent_section": row[6] or "",
            "main_section": row[7] or "",
            "page_number": row[8],
            "word_count": row[9],
            "token_estimate": row[10],
            "file_path": path,
            "doc_year": row[11],
            "doc_type": row[12] or "other",
        }
        for row in cur.fetchall()
    ]


def search_summary_files(conn: sqlite3.Connection, query: str, limit: int = 3) -> list[dict]:
    """BM25 search over per-file summaries; returns matched documents."""
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    try:
        cur = conn.execute(
            """
            SELECT f.path, f.summary, summaries_fts.rank,
                   f.doc_year, f.doc_type, f.entity_name
            FROM summaries_fts
            JOIN files f ON summaries_fts.rowid = f.id
            WHERE summaries_fts MATCH ?
            ORDER BY summaries_fts.rank
            LIMIT ?
            """,
            (fts_query, limit),
        )
    except Exception:
        return []
    return [
        {
            "file_path": row[0],
            "summary": row[1] or "",
            "score": -row[2],
            "doc_year": row[3],
            "doc_type": row[4] or "other",
            "entity_name": row[5] or "",
        }
        for row in cur.fetchall()
    ]


def grep_chunks(
    conn: sqlite3.Connection,
    terms: list[str],
    *,
    limit: int = 12,
    file_paths: list[str] | None = None,
) -> list[dict]:
    """Exact/substring lookup over indexed chunk text.

    Backs the agentic RAG "look up the exact number/quote" step. Unlike FTS,
    LIKE matching finds figures, tickers and quoted phrases verbatim.
    """
    cleaned = [t.strip() for t in terms if t and len(t.strip()) >= 2]
    if not cleaned:
        return []

    conditions = []
    params: list = []
    for term in cleaned[:8]:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append("c.content LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")

    where = "(" + " OR ".join(conditions) + ")"
    if file_paths:
        placeholders = ",".join("?" * len(file_paths))
        where += f" AND f.path IN ({placeholders})"
        params.extend(file_paths)
    params.append(limit)

    cur = conn.execute(
        f"""
        SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
               c.section_title, c.subsection, c.parent_section, c.main_section,
               c.page_number, f.doc_year, f.doc_type, f.entity_name
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE {where}
        ORDER BY length(c.content) ASC
        LIMIT ?
        """,
        params,
    )
    return [
        {
            "chunk_db_id": row[0],
            "file_path": row[1],
            "chunk_index": row[2],
            "chunk_type": row[3],
            "content": row[4],
            "section_title": row[5] or "",
            "subsection": row[6] or "",
            "parent_section": row[7] or "",
            "main_section": row[8] or "",
            "page_number": row[9],
            "doc_year": row[10],
            "doc_type": row[11] or "other",
            "entity_name": row[12] or "",
            "search_type": "exact",
        }
        for row in cur.fetchall()
    ]


def build_fts_query(query: str, mode: str = "any") -> str:
    """Turn raw user text into a safe FTS5 query.

    ``mode="any"`` emits an OR-of-prefixes query (high recall). ``mode="all"``
    emits an AND-of-prefixes query (high precision) used as an extra ranked
    list during fusion. Each term is quoted so FTS5 operators in user text
    ("-", AND/OR/NOT, quotes, parens, "col:") can never cause a syntax error.
    Returns ``""`` if nothing usable.
    """
    import re as _re

    safe_query = _re.sub(r"[^\w\s\-]", " ", query, flags=_re.UNICODE).strip()
    terms = [w for w in safe_query.split() if len(w.strip("-")) >= 2]
    if not terms:
        return ""
    joiner = " AND " if str(mode).lower() == "all" else " OR "
    return joiner.join(f'"{w}"*' for w in terms)


def fts_search(
    conn: sqlite3.Connection, query: str, limit: int = 5, *, mode: str = "any"
) -> list[dict]:
    """Perform a BM25 keyword search using FTS5."""
    fts_query = build_fts_query(query, mode=mode)
    if not fts_query:
        return []

    try:
        cur = conn.execute(
            """
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.subsection, c.parent_section, c.main_section,
                   c.page_number, f.doc_year, f.doc_type, f.entity_name
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN files f ON c.file_id = f.id
            WHERE chunks_fts MATCH ?
            ORDER BY chunks_fts.rank
            LIMIT ?
            """,
            (fts_query, limit),
        )
    except Exception:
        return []

    results = []
    for row in cur.fetchall():
        results.append(
            {
                "chunk_db_id": row[0],
                "file_path": row[1],
                "chunk_index": row[2],
                "chunk_type": row[3],
                "content": row[4],
                "score": -row[5],
                "section_title": row[6] or "",
                "subsection": row[7] or "",
                "parent_section": row[8] or "",
                "main_section": row[9] or "",
                "page_number": row[10],
                "doc_year": row[11],
                "doc_type": row[12] or "other",
                "entity_name": row[13] or "",
            }
        )
    return results


def fts_search_filtered(
    conn: sqlite3.Connection,
    query: str,
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
    subsection: str | None = None,
    file_paths: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """BM25 search with optional metadata filters on the JOIN side."""
    fts_query = build_fts_query(query)
    if not fts_query:
        return []

    conditions = ["chunks_fts MATCH ?"]
    params: list = [fts_query]

    if doc_year is not None:
        conditions.append("f.doc_year = ?")
        params.append(doc_year)
    if doc_type is not None:
        conditions.append("f.doc_type = ?")
        params.append(doc_type)
    if entity_name is not None:
        conditions.append("f.entity_name LIKE ?")
        params.append(f"%{entity_name}%")
    if section_title is not None:
        conditions.append(
            "(c.section_title LIKE ? OR c.subsection LIKE ? OR c.parent_section LIKE ?)"
        )
        params.extend([f"%{section_title}%", f"%{section_title}%", f"%{section_title}%"])
    if subsection is not None:
        conditions.append("c.subsection LIKE ?")
        params.append(f"%{subsection}%")
    if file_paths is not None:
        placeholders = ",".join("?" * len(file_paths))
        conditions.append(f"f.path IN ({placeholders})")
        params.extend(file_paths)

    where_clause = " AND ".join(conditions)
    params.append(limit)

    try:
        cur = conn.execute(
            f"""
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.subsection, c.parent_section, c.main_section,
                   c.page_number, f.doc_year, f.doc_type, f.entity_name
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN files f ON c.file_id = f.id
            WHERE {where_clause}
            ORDER BY chunks_fts.rank
            LIMIT ?
            """,
            params,
        )
    except Exception:
        return []

    results = []
    for row in cur.fetchall():
        results.append(
            {
                "chunk_db_id": row[0],
                "file_path": row[1],
                "chunk_index": row[2],
                "chunk_type": row[3],
                "content": row[4],
                "score": -row[5],
                "section_title": row[6] or "",
                "subsection": row[7] or "",
                "parent_section": row[8] or "",
                "main_section": row[9] or "",
                "page_number": row[10],
                "doc_year": row[11],
                "doc_type": row[12] or "other",
                "entity_name": row[13] or "",
            }
        )
    return results


def get_candidate_chunk_ids(
    conn: sqlite3.Connection,
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
    subsection: str | None = None,
    file_paths: list[str] | None = None,
) -> set[int]:
    """Return a set of chunk IDs matching the given metadata filters."""
    conditions = []
    params: list = []

    if doc_year is not None:
        conditions.append("f.doc_year = ?")
        params.append(doc_year)
    if doc_type is not None:
        conditions.append("f.doc_type = ?")
        params.append(doc_type)
    if entity_name is not None:
        conditions.append("f.entity_name LIKE ?")
        params.append(f"%{entity_name}%")
    if section_title is not None:
        conditions.append(
            "(c.section_title LIKE ? OR c.subsection LIKE ? OR c.parent_section LIKE ?)"
        )
        params.extend([f"%{section_title}%", f"%{section_title}%", f"%{section_title}%"])
    if subsection is not None:
        conditions.append("c.subsection LIKE ?")
        params.append(f"%{subsection}%")
    if file_paths is not None:
        placeholders = ",".join("?" * len(file_paths))
        conditions.append(f"f.path IN ({placeholders})")
        params.extend(file_paths)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cur = conn.execute(
        f"""
        SELECT c.id FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE {where_clause}
        """,
        params,
    )
    return {row[0] for row in cur.fetchall()}


# ── knowledge sources ────────────────────────────────────────────────────────

SOURCE_COLUMNS = (
    "id",
    "kind",
    "url",
    "canonical_url",
    "title",
    "author",
    "site",
    "published_at",
    "fetched_at",
    "etag",
    "last_modified",
    "content_hash",
    "file_path",
    "snapshot_path",
    "status",
    "error",
    "note",
    "tags",
    "reading_state",
    "favorite",
    "refresh_interval",
    "last_checked",
    "parent_id",
    "change_summary",
    "created_at",
    "updated_at",
)


def _source_dict(row) -> dict:
    return {name: row[index] for index, name in enumerate(SOURCE_COLUMNS)}


def upsert_source(conn: sqlite3.Connection, source: dict) -> dict:
    """Insert or update one source row and return the persisted record."""
    values = {name: source.get(name) for name in SOURCE_COLUMNS}
    values["tags"] = values.get("tags") or "[]"
    values["status"] = values.get("status") or "queued"
    values["reading_state"] = values.get("reading_state") or "unread"
    values["favorite"] = int(values.get("favorite") or 0)
    conn.execute(
        f"""
        INSERT INTO sources ({", ".join(SOURCE_COLUMNS)})
        VALUES ({", ".join("?" * len(SOURCE_COLUMNS))})
        ON CONFLICT(id) DO UPDATE SET
            kind=excluded.kind,
            url=excluded.url,
            canonical_url=excluded.canonical_url,
            title=excluded.title,
            author=excluded.author,
            site=excluded.site,
            published_at=excluded.published_at,
            fetched_at=excluded.fetched_at,
            etag=excluded.etag,
            last_modified=excluded.last_modified,
            content_hash=excluded.content_hash,
            file_path=excluded.file_path,
            snapshot_path=excluded.snapshot_path,
            status=excluded.status,
            error=excluded.error,
            note=excluded.note,
            tags=excluded.tags,
            reading_state=excluded.reading_state,
            favorite=excluded.favorite,
            refresh_interval=excluded.refresh_interval,
            last_checked=excluded.last_checked,
            updated_at=excluded.updated_at
        """,
        tuple(values[name] for name in SOURCE_COLUMNS),
    )
    conn.commit()
    return get_source(conn, str(values["id"])) or values


def get_source(conn: sqlite3.Connection, source_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources WHERE id = ?",
        (str(source_id or ""),),
    ).fetchone()
    return _source_dict(row) if row is not None else None


def find_source(
    conn: sqlite3.Connection,
    *,
    canonical_url: str = "",
    file_path: str = "",
) -> dict | None:
    if canonical_url:
        row = conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources WHERE canonical_url = ?",
            (canonical_url,),
        ).fetchone()
        if row is not None:
            return _source_dict(row)
    if file_path:
        row = conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row is not None:
            return _source_dict(row)
    return None


def list_sources(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    kind: str = "",
    status: str = "",
    reading_state: str = "",
    collection_id: str = "",
    favorite: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[dict], int]:
    where: list[str] = []
    params: list = []
    if q:
        where.append("(title LIKE ? OR url LIKE ? OR site LIKE ? OR note LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if status:
        where.append("status = ?")
        params.append(status)
    if reading_state:
        where.append("reading_state = ?")
        params.append(reading_state)
    if favorite is not None:
        where.append("favorite = ?")
        params.append(int(favorite))
    if collection_id:
        where.append(
            "id IN (SELECT source_id FROM source_collections WHERE collection_id = ?)"
        )
        params.append(collection_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM sources {clause}", tuple(params)).fetchone()[0]
        or 0
    )
    rows = conn.execute(
        f"""
        SELECT {", ".join(SOURCE_COLUMNS)} FROM sources {clause}
        ORDER BY COALESCE(fetched_at, created_at, 0) DESC, id
        LIMIT ? OFFSET ?
        """,
        (*params, max(1, min(int(limit or 200), 1000)), max(0, int(offset or 0))),
    ).fetchall()
    return [_source_dict(row) for row in rows], total


def delete_source(conn: sqlite3.Connection, source_id: str) -> bool:
    cur = conn.execute("DELETE FROM sources WHERE id = ?", (str(source_id or ""),))
    conn.execute(
        "DELETE FROM source_collections WHERE source_id = ?", (str(source_id or ""),)
    )
    conn.commit()
    return cur.rowcount > 0


def set_source_status(
    conn: sqlite3.Connection, source_id: str, status: str, error: str = ""
) -> None:
    conn.execute(
        "UPDATE sources SET status = ?, error = ?, updated_at = ? WHERE id = ?",
        (status, error, __import__("time").time(), str(source_id)),
    )
    conn.commit()


def attach_collection(conn: sqlite3.Connection, source_id: str, collection_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO source_collections(source_id, collection_id) VALUES (?, ?)",
        (str(source_id), str(collection_id)),
    )
    conn.commit()


def detach_collection(conn: sqlite3.Connection, source_id: str, collection_id: str) -> None:
    conn.execute(
        "DELETE FROM source_collections WHERE source_id = ? AND collection_id = ?",
        (str(source_id), str(collection_id)),
    )
    conn.commit()


def list_collections(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.id, c.name, c.description, c.created_at, c.updated_at,
               COUNT(sc.source_id) AS source_count
        FROM collections c
        LEFT JOIN source_collections sc ON sc.collection_id = c.id
        GROUP BY c.id ORDER BY c.name COLLATE NOCASE
        """
    ).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2] or "",
            "created_at": row[3],
            "updated_at": row[4],
            "source_count": int(row[5] or 0),
        }
        for row in rows
    ]
