import typer
import time
from pathlib import Path
from core.config import write_default_config, palimind_dir, load_config
from core.cli.ui import print_header, print_success, print_error, print_info, create_progress, console
from core.storage.db import init_db, get_connection, upsert_file, delete_file, insert_chunks
from core.storage.vector_store import delete_vectors_for_file, insert_vectors
from core.ingestion.crawler import crawl_directory, compute_md5
from core.ingestion.chunker import chunk_text
from core.ingestion.doc_parser import parse_document
from core.ingestion.image_parser import caption_image
from core.retrieval.embedder import generate_embeddings_batch
from core.retrieval.searcher import retrieve_context
from core.generative.responder import generate_response_stream

app = typer.Typer(help="Palimind - Local Multimodal RAG CLI")

@app.command()
def init(path: Path = typer.Argument(..., help="Path to initialize indexing")):
    """Initialize a new index in the specified directory."""
    target_dir = path.resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        print_error(f"Directory {target_dir} does not exist.")
        raise typer.Exit(1)
    
    print_header("Initializing Palimind Index")
    
    p_dir = palimind_dir(target_dir)
    if p_dir.exists():
        print_info(f"Index already exists at {p_dir}. Use 'pm add' to update.")
        raise typer.Exit(0)
    
    write_default_config(target_dir)
    init_db(target_dir)
    
    print_success(f"Initialized empty index at {p_dir}")
    print_info("Run 'pm add .' to start indexing files.")

def process_file(file_path: Path, root: Path, config: dict) -> list:
    """Returns a list of dicts: {"content": str, "type": str}"""
    ext = file_path.suffix.lower()
    
    if ext in config["image_extensions"]:
        caption = caption_image(file_path, config["ollama_base_url"], config["vision_model"])
        if caption:
            return [{"content": caption, "type": "caption"}]
        return []
        
    text = ""
    if ext in config["doc_extensions"]:
        text = parse_document(file_path)
    elif ext in config["extensions"]: # text files
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            pass
            
    chunks = chunk_text(text, config["chunk_size"], config["chunk_overlap"])
    return [{"content": c, "type": "text"} for c in chunks]

@app.command()
def add(path: Path = typer.Argument(Path("."), help="Path to the indexed directory")):
    """Update an existing index with new or modified files."""
    target_dir = path.resolve()
    p_dir = palimind_dir(target_dir)
    if not p_dir.exists():
        print_error(f"No index found in {target_dir}. Run 'pm init' first.")
        raise typer.Exit(1)
    
    print_header("Updating Index")
    config = load_config(target_dir)
    init_db(target_dir)
    
    with create_progress() as progress:
        crawl_task = progress.add_task("[cyan]Crawling directory...", total=None)
        new_or_modified, unchanged, deleted = crawl_directory(target_dir)
        progress.update(crawl_task, completed=100, description=f"[cyan]Found {len(new_or_modified)} to index, {len(deleted)} to delete.")
        
        conn = get_connection(target_dir)
        
        if deleted:
            del_task = progress.add_task("[red]Removing deleted files...", total=len(deleted))
            for d in deleted:
                delete_vectors_for_file(target_dir, d)
                delete_file(conn, d)
                progress.advance(del_task)
                
        if new_or_modified:
            idx_task = progress.add_task("[green]Indexing files...", total=len(new_or_modified))
            
            for fpath in new_or_modified:
                rel_path = str(fpath.relative_to(target_dir))
                md5 = compute_md5(fpath)
                
                # Cleanup old vectors if modified
                delete_vectors_for_file(target_dir, rel_path)
                file_id = upsert_file(conn, rel_path, md5, time.time())
                
                # Extract text/captions
                chunks_info = process_file(fpath, target_dir, config)
                
                if chunks_info:
                    texts = [c["content"] for c in chunks_info]
                    # Embed
                    embeddings = generate_embeddings_batch(texts, config["ollama_base_url"], config["embed_model"])
                    
                    vector_data = []
                    db_chunks = []
                    for i, (info, emb) in enumerate(zip(chunks_info, embeddings)):
                        if not emb:
                            continue
                        db_chunks.append((i, info["type"], info["content"]))
                        vector_data.append({
                            "vector": emb,
                            "file_path": rel_path,
                            "chunk_index": i,
                            "chunk_type": info["type"],
                            "content": info["content"]
                        })
                        
                    if vector_data:
                        insert_vectors(target_dir, vector_data)
                        insert_chunks(conn, file_id, db_chunks)
                        
                progress.advance(idx_task)
                
        conn.close()
    
    print_success("Index updated.")

@app.command()
def ask(
    query: str = typer.Argument(..., help="Question to ask"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Path to the indexed directory")
):
    """Ask a question against the indexed knowledge base."""
    target_dir = path.resolve()
    p_dir = palimind_dir(target_dir)
    if not p_dir.exists():
        print_error(f"No index found in {target_dir}.")
        raise typer.Exit(1)
        
    config = load_config(target_dir)
    sys_prompt_path = target_dir / "core" / "generative" / "templates" / "system.md"
    sys_prompt = ""
    # We fallback to hardcoded if not found in template for safety, but let's check package path
    # Actually, it's safer to just provide a default string if file doesn't exist
    sys_prompt = "You are a helpful assistant. Use the provided context to answer the question."
    
    print_header("Answering Question")
    print_info(f"Retrieving context for: {query}")
    
    context_data = retrieve_context(query, target_dir)
    texts = context_data["text_contexts"]
    images = context_data["image_paths"]
    
    if not texts and not images:
        print_error("No relevant context found in index.")
        return
        
    joined_context = "\n\n".join(texts)
    
    print_info("Generating response...")
    stream = generate_response_stream(
        query=query,
        context=joined_context,
        image_paths=images,
        ollama_url=config["ollama_base_url"],
        chat_model=config["chat_model"],
        system_prompt=sys_prompt
    )
    
    # We can use rich live or just print token by token
    console.print("[bold magenta]Palimind:[/bold magenta] ", end="")
    for token in stream:
        print(token, end="", flush=True)
    print()

@app.command()
def chat(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Path to the indexed directory")
):
    """Start an interactive chat session."""
    target_dir = path.resolve()
    if not palimind_dir(target_dir).exists():
        print_error(f"No index found in {target_dir}.")
        raise typer.Exit(1)
    
    print_header("Interactive Chat")
    print_info("Type 'exit' or 'quit' to end the session.")
    
    while True:
        try:
            user_input = input("\nYou> ")
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input.strip():
                continue
            
            ask(query=user_input, path=target_dir)
            
        except (KeyboardInterrupt, EOFError):
            break
