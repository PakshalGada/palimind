import hashlib
import os
from pathlib import Path
from core.config import load_config
from core.storage.db import get_connection, get_file_hash, upsert_file, delete_file
from core.storage.vector_store import delete_vectors_for_file

def compute_md5(file_path: Path) -> str:
    hasher = hashlib.md5()
    try:
        with file_path.open('rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""

def crawl_directory(root: Path) -> tuple[list[Path], list[Path], list[str]]:
    """
    Returns: (new_or_modified_files, unchanged_files, deleted_paths)
    """
    config = load_config(root)
    allowed_exts = set(config["extensions"] + config["doc_extensions"] + config["image_extensions"])
    
    conn = get_connection(root)
    
    # Get all currently indexed paths
    cur = conn.cursor()
    cur.execute("SELECT path, md5_hash FROM files")
    indexed_files = {row[0]: row[1] for row in cur.fetchall()}
    
    current_files = []
    
    # Walk directory
    for dirpath, dirnames, filenames in os.walk(root):
        # Exclude hidden directories
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        
        for filename in filenames:
            if filename.startswith('.'):
                continue
                
            file_path = Path(dirpath) / filename
            if file_path.suffix.lower() in allowed_exts:
                current_files.append(file_path)
                
    new_or_modified = []
    unchanged = []
    
    current_paths = set()
    for file_path in current_files:
        path_str = str(file_path.relative_to(root))
        current_paths.add(path_str)
        
        current_hash = compute_md5(file_path)
        if not current_hash:
            continue
            
        old_hash = indexed_files.get(path_str)
        
        if old_hash != current_hash:
            new_or_modified.append(file_path)
        else:
            unchanged.append(file_path)
            
    # Find deleted files
    deleted_paths = []
    for path_str in indexed_files:
        if path_str not in current_paths:
            deleted_paths.append(path_str)
            
    conn.close()
    return new_or_modified, unchanged, deleted_paths
