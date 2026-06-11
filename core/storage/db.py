from __future__ import annotations

import sqlite3
from pathlib import Path

from core.config import db_path


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
            ("summary",     "TEXT DEFAULT ''"),
            ("doc_year",    "INTEGER"),
            ("doc_type",    "TEXT DEFAULT 'other'"),
            ("entity_name", "TEXT DEFAULT ''"),
            ("total_pages", "INTEGER"),
            ("language",    "TEXT DEFAULT 'en'"),
        ]:
            col_name, col_type = col_def
            if col_name not in file_cols:
                cur.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")

        cur.execute("PRAGMA table_info(chunks)")
        chunk_cols = {col[1] for col in cur.fetchall()}
        for col_def in [
            ("section_title",  "TEXT DEFAULT ''"),
            ("parent_section", "TEXT DEFAULT ''"),
            ("page_number",    "INTEGER"),
            ("word_count",     "INTEGER"),
            ("token_estimate", "INTEGER"),
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

        # ── financial_facts ───────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS financial_facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     INTEGER NOT NULL,
                chunk_id    INTEGER,
                metric_name TEXT NOT NULL,
                value       REAL,
                unit        TEXT DEFAULT 'USD',
                period      TEXT DEFAULT '',
                doc_year    INTEGER,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_financial_facts_metric
            ON financial_facts(metric_name, doc_year)
        """)

        # ── timeline_events ───────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     INTEGER NOT NULL,
                chunk_id    INTEGER,
                event_date  TEXT DEFAULT '',
                event_year  INTEGER,
                event_text  TEXT NOT NULL,
                event_type  TEXT DEFAULT 'general',
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_events_date
            ON timeline_events(event_date, event_year)
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
    ``(chunk_index, chunk_type, content, section_title, parent_section, page_number, word_count, token_estimate)``
    or legacy ``(chunk_index, chunk_type, content)``.
    Returns ``list[int]`` of inserted row IDs in the same order.
    """
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    chunk_ids: list[int] = []
    cur = conn.cursor()
    for row in chunks_data:
        if len(row) == 3:
            idx, ctype, content = row
            section_title = ""
            parent_section = ""
            page_number = None
            word_count = None
            token_estimate = None
        else:
            idx, ctype, content, section_title, parent_section, page_number, word_count, token_estimate = row
        cur.execute(
            """INSERT INTO chunks
               (file_id, chunk_index, chunk_type, content,
                section_title, parent_section, page_number, word_count, token_estimate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, idx, ctype, content,
             section_title or "", parent_section or "",
             page_number, word_count, token_estimate),
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


def get_chunks_for_file(conn: sqlite3.Connection, path: str) -> list[str]:
    """Return all chunk contents for a given file path, ordered by chunk_index."""
    cur = conn.execute(
        """
        SELECT c.content
        FROM chunks c
        JOIN files f ON c.file_id = f.id
        WHERE f.path = ?
          AND c.chunk_type IN ('text', 'caption')
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
               c.section_title, c.parent_section, c.page_number,
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
            "parent_section": row[5] or "",
            "page_number": row[6],
            "word_count": row[7],
            "token_estimate": row[8],
            "file_path": path,
            "doc_year": row[9],
            "doc_type": row[10] or "other",
            "entity_name": row[11] or "",
        }
        for row in cur.fetchall()
    ]


def fts_search(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Perform a BM25 keyword search using FTS5."""
    import re as _re
    safe_query = _re.sub(r'[^\w\s\-]', ' ', query, flags=_re.UNICODE).strip()

    if not safe_query:
        return []

    terms = [f"{w}*" for w in safe_query.split() if len(w) >= 2]
    if not terms:
        return []
    fts_query = " OR ".join(terms)

    try:
        cur = conn.execute(
            '''
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.parent_section, c.page_number,
                   f.doc_year, f.doc_type, f.entity_name
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN files f ON c.file_id = f.id
            WHERE chunks_fts MATCH ?
            ORDER BY chunks_fts.rank
            LIMIT ?
            ''',
            (fts_query, limit)
        )
    except Exception:
        return []

    results = []
    for row in cur.fetchall():
        results.append({
            "chunk_db_id": row[0],
            "file_path": row[1],
            "chunk_index": row[2],
            "chunk_type": row[3],
            "content": row[4],
            "score": -row[5],
            "section_title": row[6] or "",
            "parent_section": row[7] or "",
            "page_number": row[8],
            "doc_year": row[9],
            "doc_type": row[10] or "other",
            "entity_name": row[11] or "",
        })
    return results


def fts_search_filtered(
    conn: sqlite3.Connection,
    query: str,
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """BM25 search with optional metadata filters on the JOIN side."""
    import re as _re
    safe_query = _re.sub(r'[^\w\s\-]', ' ', query, flags=_re.UNICODE).strip()
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
        conditions.append("c.section_title LIKE ?")
        params.append(f"%{section_title}%")

    where_clause = " AND ".join(conditions)
    params.append(limit)

    try:
        cur = conn.execute(
            f"""
            SELECT c.id, f.path, c.chunk_index, c.chunk_type, c.content,
                   chunks_fts.rank,
                   c.section_title, c.parent_section, c.page_number,
                   f.doc_year, f.doc_type, f.entity_name
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN files f ON c.file_id = f.id
            WHERE {where_clause}
            ORDER BY chunks_fts.rank
            LIMIT ?
            """,
            params
        )
    except Exception:
        return []

    results = []
    for row in cur.fetchall():
        results.append({
            "chunk_db_id": row[0],
            "file_path": row[1],
            "chunk_index": row[2],
            "chunk_type": row[3],
            "content": row[4],
            "score": -row[5],
            "section_title": row[6] or "",
            "parent_section": row[7] or "",
            "page_number": row[8],
            "doc_year": row[9],
            "doc_type": row[10] or "other",
            "entity_name": row[11] or "",
        })
    return results


def get_candidate_chunk_ids(
    conn: sqlite3.Connection,
    *,
    doc_year: int | None = None,
    doc_type: str | None = None,
    entity_name: str | None = None,
    section_title: str | None = None,
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
        conditions.append("c.section_title LIKE ?")
        params.append(f"%{section_title}%")
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


# ── financial_facts ────────────────────────────────────────────────────────────

def insert_financial_facts(
    conn: sqlite3.Connection,
    file_id: int,
    facts: list[dict],
) -> None:
    """Insert financial facts for a file. Each dict has keys: metric_name, value, unit, period, doc_year, chunk_id."""
    conn.execute("DELETE FROM financial_facts WHERE file_id = ?", (file_id,))
    for fact in facts:
        conn.execute(
            """INSERT INTO financial_facts
               (file_id, chunk_id, metric_name, value, unit, period, doc_year)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                file_id,
                fact.get("chunk_id"),
                fact["metric_name"],
                fact.get("value"),
                fact.get("unit", "USD"),
                fact.get("period", ""),
                fact.get("doc_year"),
            ),
        )


def query_financial_facts(
    conn: sqlite3.Connection,
    *,
    metric_names: list[str] | None = None,
    doc_year_min: int | None = None,
    doc_year_max: int | None = None,
    limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list = []

    if metric_names:
        placeholders = ",".join("?" * len(metric_names))
        conditions.append(f"ff.metric_name IN ({placeholders})")
        params.extend(metric_names)
    if doc_year_min is not None:
        conditions.append("ff.doc_year >= ?")
        params.append(doc_year_min)
    if doc_year_max is not None:
        conditions.append("ff.doc_year <= ?")
        params.append(doc_year_max)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)

    cur = conn.execute(
        f"""
        SELECT ff.metric_name, ff.value, ff.unit, ff.period, ff.doc_year, f.path
        FROM financial_facts ff
        JOIN files f ON ff.file_id = f.id
        WHERE {where_clause}
        ORDER BY ff.doc_year, ff.metric_name
        LIMIT ?
        """,
        params,
    )
    return [
        {
            "metric_name": row[0],
            "value": row[1],
            "unit": row[2],
            "period": row[3],
            "doc_year": row[4],
            "file_path": row[5],
        }
        for row in cur.fetchall()
    ]


# ── timeline_events ────────────────────────────────────────────────────────────

def insert_timeline_events(
    conn: sqlite3.Connection,
    file_id: int,
    events: list[dict],
) -> None:
    """Insert timeline events for a file."""
    conn.execute("DELETE FROM timeline_events WHERE file_id = ?", (file_id,))
    for event in events:
        conn.execute(
            """INSERT INTO timeline_events
               (file_id, chunk_id, event_date, event_year, event_text, event_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                file_id,
                event.get("chunk_id"),
                event.get("event_date", ""),
                event.get("event_year"),
                event["event_text"],
                event.get("event_type", "general"),
            ),
        )


def query_timeline_events(
    conn: sqlite3.Connection,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    event_types: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    conditions = []
    params: list = []

    if year_min is not None:
        conditions.append("te.event_year >= ?")
        params.append(year_min)
    if year_max is not None:
        conditions.append("te.event_year <= ?")
        params.append(year_max)
    if event_types:
        placeholders = ",".join("?" * len(event_types))
        conditions.append(f"te.event_type IN ({placeholders})")
        params.extend(event_types)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    params.append(limit)

    cur = conn.execute(
        f"""
        SELECT te.event_date, te.event_year, te.event_text, te.event_type, f.path
        FROM timeline_events te
        JOIN files f ON te.file_id = f.id
        WHERE {where_clause}
        ORDER BY te.event_date, te.event_year
        LIMIT ?
        """,
        params,
    )
    return [
        {
            "event_date": row[0],
            "event_year": row[1],
            "event_text": row[2],
            "event_type": row[3],
            "file_path": row[4],
        }
        for row in cur.fetchall()
    ]
