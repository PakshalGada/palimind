import sqlite3
from pathlib import Path
from core.config import db_path

def init_db(root: Path):
    path = db_path(root)
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    
    cur.execute("PRAGMA table_info(files)")
    columns = [col[1] for col in cur.fetchall()]
    if columns and "path" not in columns:
        cur.execute("DROP TABLE IF EXISTS chunks")
        cur.execute("DROP TABLE IF EXISTS files")
        
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE,
            md5_hash TEXT,
            last_indexed REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER,
            chunk_index INTEGER,
            chunk_type TEXT, -- 'text', 'image', 'caption'
            content TEXT,
            FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def get_connection(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    # Enable foreign keys
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_file_hash(conn: sqlite3.Connection, path: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT md5_hash FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    return row[0] if row else None

def upsert_file(conn: sqlite3.Connection, path: str, md5_hash: str, timestamp: float) -> int:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO files (path, md5_hash, last_indexed)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            md5_hash=excluded.md5_hash,
            last_indexed=excluded.last_indexed
    """, (path, md5_hash, timestamp))
    conn.commit()
    
    cur.execute("SELECT id FROM files WHERE path = ?", (path,))
    return cur.fetchone()[0]

def delete_file(conn: sqlite3.Connection, path: str):
    cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE path = ?", (path,))
    conn.commit()

def insert_chunks(conn: sqlite3.Connection, file_id: int, chunks_data: list):
    """chunks_data is list of tuples: (chunk_index, chunk_type, content)"""
    cur = conn.cursor()
    # Delete old chunks for this file
    cur.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    
    insert_data = [(file_id, idx, ctype, content) for idx, ctype, content in chunks_data]
    cur.executemany("""
        INSERT INTO chunks (file_id, chunk_index, chunk_type, content)
        VALUES (?, ?, ?, ?)
    """, insert_data)
    conn.commit()
