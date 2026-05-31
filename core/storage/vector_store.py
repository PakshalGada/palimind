import lancedb
from pathlib import Path
from core.config import lance_db_path

def get_db(root: Path):
    path = lance_db_path(root)
    return lancedb.connect(str(path))

def init_table(root: Path, dimension: int = 768):
    # Nomic-embed-text uses 768 dimensions usually. We will use PyArrow schema or dicts.
    db = get_db(root)
    # If the table already exists, just return it
    if "embeddings" in db.table_names():
        return db.open_table("embeddings")
    
    # We define a schema implicitly via initial data, or use pyarrow explicitly.
    # For flexibility, we'll wait for the first insert to create the table,
    # or define an empty pyarrow schema. Let's define an empty schema.
    import pyarrow as pa
    schema = pa.schema([
        pa.field("vector", pa.list_(pa.float32(), dimension)),
        pa.field("file_path", pa.string()),
        pa.field("chunk_index", pa.int32()),
        pa.field("chunk_type", pa.string()),
        pa.field("content", pa.string())
    ])
    
    table = db.create_table("embeddings", schema=schema)
    return table

def insert_vectors(root: Path, data: list[dict]):
    """
    data format:
    [
        {
            "vector": [0.1, 0.2, ...],
            "file_path": "a.txt",
            "chunk_index": 0,
            "chunk_type": "text",
            "content": "hello world"
        }
    ]
    """
    if not data:
        return
        
    db = get_db(root)
    dimension = len(data[0]["vector"])
    table = init_table(root, dimension)
    table.add(data)

def delete_vectors_for_file(root: Path, file_path: str):
    db = get_db(root)
    if "embeddings" in db.table_names():
        table = db.open_table("embeddings")
        table.delete(f"file_path = '{file_path}'")

def search(root: Path, query_vector: list[float], limit: int = 5):
    db = get_db(root)
    if "embeddings" not in db.table_names():
        return []
    
    table = db.open_table("embeddings")
    results = table.search(query_vector).limit(limit).to_list()
    return results
