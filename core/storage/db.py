from __future__ import annotations

import sqlite3
from pathlib import Path

from core.config import db_path


def init_db(root: Path) -> None:
    conn = sqlite3.connect(db_path(root))
    try:
        cur = conn.cursor()

        # Enable WAL mode for concurrent reads and faster writes.
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")

        cur.execute("PRAGMA table_info(files)")
        columns = [col[1] for col in cur.fetchall()]
        if columns and "path" not in columns:
            cur.execute("DROP TABLE IF EXISTS chunks")
            cur.execute("DROP TABLE IF EXISTS files")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT UNIQUE,
                md5_hash    TEXT,
                last_indexed REAL,
                summary     TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id     INTEGER,
                chunk_index INTEGER,
                chunk_type  TEXT,
                content     TEXT,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)

        # Migration: add summary column to existing databases.
        if columns and "summary" not in columns:
            cur.execute("ALTER TABLE files ADD COLUMN summary TEXT DEFAULT ''")

        conn.commit()
    finally:
        conn.close()


def get_connection(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_file_hash(conn: sqlite3.Connection, path: str) -> str | None:
    cur = conn.execute("SELECT md5_hash FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_file(conn: sqlite3.Connection, path: str, md5_hash: str, timestamp: float) -> int:
    conn.execute(
        """
        INSERT INTO files (path, md5_hash, last_indexed)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            md5_hash=excluded.md5_hash,
            last_indexed=excluded.last_indexed
        """,
        (path, md5_hash, timestamp),
    )
    cur = conn.execute("SELECT id FROM files WHERE path = ?", (path,))
    return cur.fetchone()[0]


def delete_file(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM files WHERE path = ?", (path,))


def insert_chunks(conn: sqlite3.Connection, file_id: int, chunks_data: list) -> list[int]:
    """Insert chunks and return the list of newly assigned primary key IDs.

    *chunks_data* is a list of tuples: ``(chunk_index, chunk_type, content)``.
    Returns ``list[int]`` of inserted row IDs in the same order.
    """
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    chunk_ids: list[int] = []
    cur = conn.cursor()
    for idx, ctype, content in chunks_data:
        cur.execute(
            "INSERT INTO chunks (file_id, chunk_index, chunk_type, content) VALUES (?, ?, ?, ?)",
            (file_id, idx, ctype, content),
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
    """Return a list of dicts with ``path`` and ``summary`` for every indexed file."""
    cur = conn.execute("SELECT path, summary FROM files ORDER BY path")
    return [{"path": row[0], "summary": row[1] or ""} for row in cur.fetchall()]


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
