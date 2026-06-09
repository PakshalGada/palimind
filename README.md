# Palimind

Local multimodal RAG CLI — index your codebase and documents, then query them with a local LLM.

## Features

- **Vector search** via [Turbovec](https://github.com/PakshalGada/turbovec) (4-bit compressed, O(1) deletion)
- **Intent routing** — file-targeted, corpus-wide, and semantic query strategies
- **Multimodal** — indexes text, PDF, PPTX, XLSX, and images (vision captioning + OCR)
- **Summarisation** — auto-generates per-file summaries at index time
- **Streaming responses** — token-by-token output via Ollama
- **Fully local** — all inference runs on your machine via Ollama

## Install

```bash
pip install -e .

# Optional: install OCR support (EasyOCR, heavy dependency)
pip install -e ".[ocr]"
```

## Ollama Models

```bash
ollama pull nomic-embed-text   # embeddings
ollama pull gemma4:e4b         # chat / summarisation
ollama pull llava              # vision (image captioning)
```

## Usage

```bash
cd /your/project

# Initialise the index
pm init .

# Index all files
pm add .

# Ask a question
pm ask "how does authentication work?"

# Interactive chat
pm chat
```

## Configuration

Settings are stored in `.palimind/config.json`. Defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `embed_model` | `nomic-embed-text` | Ollama embedding model |
| `chat_model` | `gemma4:e4b` | Ollama chat model |
| `vision_model` | `llava` | Ollama vision model |
| `chunk_size` | `1000` | Characters per chunk |
| `chunk_overlap` | `200` | Overlap between chunks |
| `turbovec_bit_width` | `4` | Compression (2 or 4 bit) |
| `summarise` | `true` | Generate file summaries |
