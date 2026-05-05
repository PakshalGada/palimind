import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT UNIQUE NOT NULL,
    file_hash   TEXT NOT NULL,
    last_indexed TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_text  TEXT NOT NULL,
    source_path TEXT NOT NULL,
    start_char  INTEGER NOT NULL,
    end_char    INTEGER NOT NULL,
    file_hash   TEXT NOT NULL,
    embedding   BLOB NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def is_file_indexed(self, file_path: str, file_hash: str) -> bool:
        """Return True if the file has already been indexed with this hash."""
        row = self._conn.execute(
            "SELECT file_hash FROM files WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row is not None and row[0] == file_hash

    def mark_file_indexed(self, file_path: str, file_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO files (file_path, file_hash, last_indexed)
            VALUES (?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_hash = excluded.file_hash,
                last_indexed = excluded.last_indexed
            """,
            (file_path, file_hash, now),
        )
        self._conn.commit()

    def insert_chunk(
        self,
        chunk_text: str,
        source_path: str,
        start_char: int,
        end_char: int,
        file_hash: str,
        embedding: list[float],
    ) -> None:
        vec = np.array(embedding, dtype=np.float32).tobytes()
        self._conn.execute(
            """
            INSERT INTO chunks
                (chunk_text, source_path, start_char, end_char, file_hash, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (chunk_text, source_path, start_char, end_char, file_hash, vec),
        )
        # Callers commit in bulk via commit()

    def commit(self) -> None:
        self._conn.commit()

    def delete_chunks_for_file(self, source_path: str) -> None:
        self._conn.execute("DELETE FROM chunks WHERE source_path = ?", (source_path,))
        self._conn.execute("DELETE FROM files WHERE file_path = ?", (source_path,))
        self._conn.commit()

    def get_chunk(self, chunk_id: int) -> tuple[str, str] | None:
        """Return (chunk_text, source_path) for a chunk id, or None."""
        row = self._conn.execute(
            "SELECT chunk_text, source_path FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        return row  # type: ignore[return-value]

    def load_all_embeddings(self) -> tuple[np.ndarray, list[int]]:
        """
        Return (matrix, ids) where matrix is shape (N, D) float32
        and ids is the list of chunk row ids in the same order.
        """
        rows = self._conn.execute("SELECT id, embedding FROM chunks").fetchall()
        if not rows:
            return np.empty((0, 0), dtype=np.float32), []

        ids = [r[0] for r in rows]
        vecs = [np.frombuffer(r[1], dtype=np.float32) for r in rows]
        return np.stack(vecs), ids

    def close(self) -> None:
        self._conn.close()
