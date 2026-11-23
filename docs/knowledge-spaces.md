# Knowledge spaces

A knowledge space is a container for everything a user wants to search. It is
backed by a real folder anywhere on disk, so it stays portable and readable
while reusing the existing local RAG stack.

## Model

```text
Space (registry)
  ├─ root folder (any path, created or linked)
  ├─ sources table (web pages, notes, PDFs, feeds)
  ├─ files/chunks/vectors (existing index)
  └─ graph (file/entity/section nodes + source provenance)
```

- **managed** — PaliMind created the folder. The user only chose a parent.
- **linked** — the user pointed at an existing folder; it is indexed in place.
- **project:<id>** — a project keeps its private index, unchanged.

Spaces are stored in the global state DB (`knowledge_spaces` namespace) with
`{id, name, slug, root, kind, source_dir, icon, note}`. On startup, folders in
the legacy `fields` config are adopted as linked spaces; `/api/fields/*`
continues to work as a compatibility layer.

## Source layout

```text
<space root>/
  .palimind/                    # index.db, config.json, doc_graph.json
    raw/web/<source_id>.html    # offline snapshot
  sources/
    web/<slug>-<id>.md          # YAML front-matter + article Markdown
    text/<slug>-<id>.md         # pasted notes
    files/<slug>-<id>.pdf       # PDFs captured from a URL
```

Front matter carries `source_id`, `url`, `canonical_url`, `title`, `author`,
`site`, `published_at`, `fetched_at` and `content_hash`. The indexer strips the
front matter before chunking, so it never pollutes embeddings.

## Ingestion

Web capture (`spaces/web_source.py`):

1. Normalise the URL; reject non-http(s) and private/internal addresses.
2. Re-check the SSRF guard on **every** redirect hop.
3. Check `robots.txt` (cached per origin).
4. Cap the response at 5 MB; reject non-HTML except PDF.
5. Extract readable content (`trafilatura` if installed, BeautifulSoup
   `article`/`main` fallback).
6. Read title, author, site, publish date and canonical link.
7. Write Markdown + an HTML snapshot.
8. Enqueue a durable `web_ingest` job, then an index run.

Deduplication uses the canonical URL and the content hash. Refreshes send
`If-None-Match` / `If-Modified-Since`; unchanged pages keep their copy, changed
pages are rewritten and diffed into a short "N lines added / removed" summary.

Feeds (`spaces/feeds.py`) parse RSS 2.0 and Atom with the standard library.
A feed row has `kind=feed`; each item becomes a normal web source with
`parent_id` pointing at the feed. Items then follow the same capture path.

PDF links are downloaded into `sources/files/` and parsed by the existing PDF
pipeline, so pages, sections and citations behave like any other document.

YouTube links are fetched through the public watch page caption tracks (no API
key) and saved as a timestamped transcript source. A one-level **site crawl**
saves the starting page and up to 50 same-host links, never leaving the domain.
When a live page fails with a network/HTTP error, the ingest step asks the
Internet Archive for the closest snapshot and marks the copy `web.archive.org`.
Sources also get deterministic auto-tags from the page body (no model call) when
the user has not supplied tags.

## Freshness and reading workflow

- `reading_state`: `unread → reading → read → archived`.
- `favorite`, `tags`, `note`, `collections`.
- `refresh_interval` (seconds) opts a source into the background maintenance
  loop (`spaces/maintenance.py`); sources without it are never crawled
  automatically.
- Failed/blocked sources keep their error and a retry action; the reader can
  still show the last snapshot.

## Provenance

Metadata is denormalised onto `files` (`source_id`, `source_kind`, `source_url`,
`source_title`, `source_site`, `source_author`, `source_published_at`,
`source_fetched_at`) and included in vector metadata. Retrieval enriches every
selected chunk (including expanded parents/windows) and emits:

```text
--- Source: Example Article (example.com) — https://example.com/post, fetched 2026-11-20 → Intro (Type: web) ---
```

`document/stream.py` forwards the same fields into citations, where
`build_bibliography` renders `[Example Article](https://example.com/post)`.
Graph file nodes also carry the URL, site and fetch date.

## API surface

| Endpoint | Purpose |
| --- | --- |
| `GET/POST /api/spaces` | List, create (`mode=create`) or link (`mode=link`) |
| `PATCH/DELETE /api/spaces/{id}` | Rename/metadata, remove (files kept by default) |
| `POST /api/spaces/{id}/activate` | Active space for chat/retrieval |
| `POST /api/spaces/{id}/sources` | Save `url`, `urls[]`, or `text` |
| `GET /api/spaces/{id}/sources` | Search/filter sources |
| `GET /api/spaces/{id}/sources/{sid}` | Source metadata |
| `GET .../content` | Reader content |
| `PATCH/DELETE .../{sid}` | Update metadata / remove |
| `POST .../{sid}/refresh` | Conditional refresh (or feed refresh) |
| `POST .../{sid}/reindex` | Force re-embedding |
| `POST /api/spaces/{id}/feeds` | Subscribe to RSS/Atom |
| `POST /api/spaces/{id}/crawl` | One-level same-site crawl |
| `GET/POST /api/spaces/{id}/collections` | Collections |
| `POST/DELETE .../collections` | Attach/remove a source |
| `GET /api/spaces/{id}/export` | Markdown vault ZIP |
| `GET /api/spaces/{id}/graph/export?format=json\|graphml` | Graph export |

Existing document endpoints accept `scope=field|project:<id>` and
`GET /api/document/search` accepts `collection=<id>`.

## Agent integration

`knowledge_space` (`agents/tools/knowledge-space`) exposes:

- `action=search` — hybrid retrieval with cited passages;
- `action=add_url` — fetch, save and index a page;
- `action=add_note` — save pasted text.

## Security

- User-initiated capture only; no autonomous crawling unless a source opts in
  with `refresh_interval`.
- SSRF guard on initial URLs and every redirect; private, loopback, link-local
  and metadata addresses are refused.
- `robots.txt` is honoured for pages and feeds.
- Size and redirect caps; non-HTML content rejected except PDF.
- Deleting a linked space never deletes the user's files. Deleting a managed
  space moves it to `~/.palimind/trash` instead of unlinking immediately.

## Tests

```bash
cd packages/backend
python -m pytest tests/test_knowledge_api.py tests/test_spaces_api.py \
  tests/test_web_ingest.py tests/test_feeds.py \
  tests/test_source_provenance.py -q
```

The full backend suite and the frontend `npm test` / `npm run build` cover the
integration.

## Known limits

- JavaScript-rendered pages may yield no readable text; a snapshot is still
  saved when extraction succeeds.
- Paywalled/authenticated pages are not supported yet; the fetch is anonymous.
- YouTube transcripts depend on public caption tracks; videos without captions
  fail with a clear error and can still be opened in the browser.
- Contradiction detection and automated entity alias resolution are future
  graph work; provenance and source-aware graph nodes are already in place.
- PDF-from-URL is capped by the same 5 MB response limit as HTML.
