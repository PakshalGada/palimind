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
                page_number     INTEGER,
                word_count      INTEGER,
                token_estimate  INTEGER,
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
            ("page_number", "INTEGER"),
            ("word_count", "INTEGER"),
            ("token_estimate", "INTEGER"),
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

        conn.commit()
    finally:
        conn.close()


def get_connection(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


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
) -> int:
    conn.execute(
        """
        INSERT INTO files (path, md5_hash, last_indexed, doc_year, doc_type, entity_name)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            md5_hash=excluded.md5_hash,
            last_indexed=excluded.last_indexed,
            doc_year=excluded.doc_year,
            doc_type=excluded.doc_type,
            entity_name=excluded.entity_name
        """,
        (path, md5_hash, timestamp, doc_year, doc_type, entity_name),
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

    *chunks_data* is a list of tuples:
    ``(chunk_index, chunk_type, content, section_title, subsection,
      parent_section, page_number, word_count, token_estimate)``,
    optionally followed by ``(media_start_ts, media_end_ts)`` — or legacy
    ``(chunk_index, chunk_type, content)``.
    Returns ``list[int]`` of inserted row IDs in the same order.
    """
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    chunk_ids: list[int] = []
    cur = conn.cursor()
    for row in chunks_data:
        if len(row) == 3:
            idx, ctype, content = row
            section_title = ""
            subsection = ""
            parent_section = ""
            page_number = None
            word_count = None
            token_estimate = None
            media_start_ts = None
            media_end_ts = None
        elif len(row) == 9:
            (
                idx,
                ctype,
                content,
                section_title,
                subsection,
                parent_section,
                page_number,
                word_count,
                token_estimate,
            ) = row
            media_start_ts = None
            media_end_ts = None
        else:
            (
                idx,
                ctype,
                content,
                section_title,
                subsection,
                parent_section,
                page_number,
                word_count,
                token_estimate,
                media_start_ts,
                media_end_ts,
            ) = row
        cur.execute(
            """INSERT INTO chunks
               (file_id, chunk_index, chunk_type, content,
                section_title, subsection, parent_section, page_number, word_count,
                token_estimate, media_start_ts, media_end_ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id,
                idx,
                ctype,
                content,
                section_title or "",
                subsection or "",
                parent_section or "",
                page_number,
                word_count,
                token_estimate,
                media_start_ts,
                media_end_ts,
            ),
        )
        chunk_ids.append(cur.lastrowid)
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
        "SELECT path, summary, doc_year, doc_type, entity_name FROM files ORDER BY path"
    )
    return [
        {
            "path": row[0],
            "summary": row[1] or "",
            "doc_year": row[2],
            "doc_type": row[3] or "other",
            "entity_name": row[4] or "",
        }
        for row in cur.fetchall()
    ]


def get_files_with_hash(conn: sqlite3.Connection) -> list[dict]:
    """Return every indexed file with its md5 hash (used for incremental graphs)."""
    cur = conn.execute(
        "SELECT path, md5_hash, summary, doc_year, doc_type, entity_name FROM files ORDER BY path"
    )
    return [
        {
            "path": row[0],
            "md5": row[1] or "",
            "summary": row[2] or "",
            "doc_year": row[3],
            "doc_type": row[4] or "other",
            "entity_name": row[5] or "",
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
               c.section_title, c.subsection, c.parent_section, c.page_number,
               c.word_count, c.token_estimate,
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
            "page_number": row[7],
            "word_count": row[8],
            "token_estimate": row[9],
            "file_path": path,
            "doc_year": row[10],
            "doc_type": row[11] or "other",
            "entity_name": row[12] or "",
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
               c.media_start_ts, c.media_end_ts
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
        }
        for row in cur.fetchall()
    ]


def fts_search(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Perform a BM25 keyword search using FTS5."""
    import re as _re

    safe_query = _re.sub(r"[^\w\s\-]", " ", query, flags=_re.UNICODE).strip()

    if not safe_query:
        return []

    terms = [f"{w}*" for w in safe_query.split() if len(w) >= 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)

    try:
        cur = conn.execute(
            """
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.subsection, c.parent_section, c.page_number,
                   f.doc_year, f.doc_type, f.entity_name
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
                "page_number": row[9],
                "doc_year": row[10],
                "doc_type": row[11] or "other",
                "entity_name": row[12] or "",
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
    import re as _re

    safe_query = _re.sub(r"[^\w\s\-]", " ", query, flags=_re.UNICODE).strip()
    if not safe_query:
        return []
    terms = [f"{w}*" for w in safe_query.split() if len(w) >= 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)

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
                   c.section_title, c.subsection, c.parent_section, c.page_number,
                   f.doc_year, f.doc_type, f.entity_name
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
                "page_number": row[9],
                "doc_year": row[10],
                "doc_type": row[11] or "other",
                "entity_name": row[12] or "",
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



