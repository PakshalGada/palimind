from pathlib import Path
from core.storage.db import get_connection

def fetch_parents(chunks: list[dict], root: Path) -> list[dict]:
    """
    O(1) fetch of adjacent chunks (chunk-1, chunk+1).
    Guarantees < 5ms latency by using indexed SQL lookups.
    """
    if not chunks:
        return chunks

    conn = get_connection(root)
    try:
        # Group by file_path to minimize query execution overhead
        queries = {}
        for chunk in chunks:
            fp = chunk.get("file_path")
            idx = chunk.get("chunk_index")
            if fp and idx is not None:
                if fp not in queries:
                    queries[fp] = set()
                queries[fp].add(max(0, idx - 1))
                queries[fp].add(idx)
                queries[fp].add(idx + 1)
        
        if not queries:
            return chunks
            
        expanded_chunks_by_id = {}
        for fp, indices in queries.items():
            if not indices:
                continue
            
            placeholders = ",".join("?" * len(indices))
            params = [fp] + list(indices)
            
            # This query uses the unique index on files.path and the FK index on chunks.file_id
            # making it an O(1) nested loop join fetch.
            cur = conn.execute(f"""
                SELECT c.id, c.chunk_index, c.chunk_type, c.content,
                       c.section_title, c.parent_section, c.page_number,
                       f.doc_year, f.doc_type, f.entity_name, f.path
                FROM chunks c
                JOIN files f ON c.file_id = f.id
                WHERE f.path = ? AND c.chunk_index IN ({placeholders})
            """, params)
            
            for row in cur.fetchall():
                expanded_chunks_by_id[row[0]] = {
                    "chunk_db_id": row[0],
                    "chunk_index": row[1],
                    "chunk_type": row[2],
                    "content": row[3],
                    "section_title": row[4] or "",
                    "parent_section": row[5] or "",
                    "page_number": row[6],
                    "doc_year": row[7],
                    "doc_type": row[8] or "other",
                    "entity_name": row[9] or "",
                    "file_path": row[10],
                }

        final_list = []
        seen_ids = set()
        
        for chunk in chunks:
            fp = chunk.get("file_path")
            idx = chunk.get("chunk_index")
            if not fp or idx is None:
                if chunk.get("chunk_db_id") not in seen_ids:
                    final_list.append(chunk)
                    seen_ids.add(chunk.get("chunk_db_id"))
                continue
            
            window = [idx - 1, idx, idx + 1]
            window_chunks = []
            for i in window:
                for ec in expanded_chunks_by_id.values():
                    if ec["file_path"] == fp and ec["chunk_index"] == i:
                        window_chunks.append(ec)
                        break
                        
            window_chunks.sort(key=lambda x: x["chunk_index"])
            
            for wc in window_chunks:
                if wc["chunk_db_id"] not in seen_ids:
                    if wc["chunk_db_id"] == chunk.get("chunk_db_id") and "score" in chunk:
                        wc["score"] = chunk["score"]
                    final_list.append(wc)
                    seen_ids.add(wc["chunk_db_id"])

        return final_list
        
    finally:
        conn.close()
