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
- Collections double as retrieval scopes: `GET /api/document/search?collection=…`
  and `GET /api/document/graph?collection=…` restrict both search and the graph.
- A clipboard capture that is a single URL is routed through the web-source
  pipeline (`/api/select`), so the global hotkey can save links too.
- `refresh_interval` (seconds) opts a source into the background maintenance
  loop (`spaces/maintenance.py`); sources without it are never crawled
  automatically.
- Failed/blocked sources keep their error and a retry action; the reader can
  still show the last snapshot.

## Cross-space search

`GET /api/spaces/search?q=…` queries every registered space's own index,
annotates each hit with `space_id`, `space_name` and `space_root`, deduplicates
by space/file/section/URL, and returns a merged ranking plus `by_space` counts.
The Knowledge view exposes it as **Search all**.

## Daily digest

Each space can opt into a daily digest (`digest_enabled`). The maintenance loop
builds a Markdown digest from the last day of activity — saved sources, changed
pages, failures, top entities and possible contradictions — and stores it as a
normal `kind=digest` source. `POST /api/spaces/{id}/digest` creates one on
demand; generation is idempotent per day unless `force` is set.

## Graph signals

`GET /api/spaces/{id}/signals` returns deterministic, provenance-preserving
hints rather than verdicts:

- **Aliases** — entity surface forms that normalise to the same canonical name
  (`Acme Inc.`, `ACME Corporation`).
- **Possible contradictions** — sentence pairs from different files that share
  an entity and most tokens but differ in negation, an opposing term
  (increase/decrease, higher/lower) or a figure.

Every pair includes both file paths, titles, URLs, sections and quotes so the
UI can link to the evidence. The graph tab summarises the counts.

## Capture profiles

A profile attaches headers, cookies and a user agent to a domain in a space.
Matching is suffix-based, so a profile for `example.com` also covers
`app.example.com`; the longest matching domain wins. Profiles live in the
space's local SQLite database and are only sent to that host. This enables
authenticated/paywalled pages without sending the session anywhere else.

## Domain policy and quota

Each space can set `domain_mode` to `off`, `allow` or `deny` with a domain
list. The policy is enforced when a source is created, when a redirect lands on
a different host, and for feeds/crawls. A `quota_bytes` limit covers the
space's saved `sources/` and raw snapshots; going over it fails the save with a
clear error. `GET /api/spaces/{id}/usage` reports bytes, remaining space and
percentage.

## Research integration

`POST /api/spaces/{id}/sources/from-research` turns research citations into
normal sources. Passing `space_id` when adding sources to a research project
does the same automatically. When deep research finishes, cited sources are
saved into the active space if that space has **Save deep-research sources
automatically** enabled (or a `save_space_id` is passed to `/api/chat`).

## Retention and robots

- `respect_robots` (default on) controls whether `robots.txt` is enforced for
  pages, feeds and crawls. Turning it off is an explicit user choice.
- `retention_days` prunes older saved sources during maintenance, including
  their files, vectors, chunks and graph nodes. Digests and feed rows are kept;
  `POST /api/spaces/{id}/retention/prune` supports `dry_run` previews.

## Backup and restore

`GET /api/spaces/{id}/backup` creates a portable ZIP with `sources/`, the
graph/config and `sources.json` metadata. `POST /api/spaces/restore` accepts
that ZIP plus a name/parent folder, creates a new space and restores files and
source metadata. Path traversal entries are ignored.

## External capture

`POST /api/capture/link` (JSON) and `GET /api/capture/link?...` (bookmarklet /
share-sheet receipt page) save into the active space or a supplied `space_id`.
A Manifest V3 extension in `packages/browser-extension` adds a toolbar popup
and a “Save page to PaliMind” context menu. The auth middleware accepts the
bearer token from the query string for these local capture links.

## Graph intelligence

- Edges expose a `confidence` score derived from relation weight plus the
  original typed relation (`has_section`, `references`, `related`, …);
  `typed_relations` summarises counts.
- `since_year` / `until_year` filter the graph to a timeline.
- `/signals` now returns **agreements** alongside alias groups and possible
  contradictions; all keep file/quotes/URL provenance.



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
| `GET /api/spaces/search` | Search every space at once |
| `GET/POST /api/spaces/{id}/digest` | Preview / create a daily digest |
| `GET /api/spaces/{id}/digests` | Digest history |
| `GET /api/spaces/{id}/signals` | Entity aliases + possible contradictions |
| `GET/POST /api/spaces/{id}/profiles` | Capture profiles (headers/cookies) |
| `GET /api/spaces/{id}/usage` | Saved bytes, quota and percentage |
| `GET/PATCH /api/spaces/{id}/policy` | Domain allow/deny, quota, digest/research/robots/retention |
| `POST /api/spaces/{id}/retention/prune` | Preview/apply retention pruning |
| `GET /api/spaces/{id}/backup` | Portable backup ZIP |
| `POST /api/spaces/restore` | Restore a backup into a new space |
| `POST /api/capture/link` | Extension/share-sheet capture |
| `POST /api/spaces/{id}/sources/from-research` | Save research citations |
| `GET/POST /api/spaces/{id}/collections` | Collections |
| `POST/DELETE .../collections` | Attach/remove a source |
| `GET /api/spaces/{id}/export` | Markdown vault ZIP |
| `GET /api/spaces/{id}/graph/export?format=json\|graphml` | Graph export |

Existing document endpoints accept `scope=field|project:<id>` and
`GET /api/document/search` accepts `collection=<id>`.

## Agent integration

`knowledge_space` (`agents/tools/knowledge-space`) exposes:

- `action=search` — hybrid retrieval inside one space;
- `action=search_all` — cross-space retrieval with space labels;
- `action=digest` — generate the daily digest;
- `action=add_url` — fetch, save and index a page;
- `action=add_note` — save pasted text.

## Security

- User-initiated capture only; no autonomous crawling unless a source opts in
  with `refresh_interval` or a space enables daily digests.
- SSRF guard on initial URLs and every redirect; private, loopback, link-local
  and metadata addresses are refused.
- `robots.txt` is honoured for pages and feeds.
- Size and redirect caps; non-HTML content rejected except PDF.
- Domains can be allow-listed or denied per space; the check runs again after
  redirects so a public page cannot bounce to a blocked host.
- Capture profile secrets stay in the space's local SQLite file and are only
  attached to matching hosts.
- Storage quotas cap saved source bytes and snapshot bytes.
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
- Paywalled/authenticated pages are supported through capture profiles, but
  multi-step login flows and CAPTCHAs are not automated.
- Contradiction and alias signals are deterministic heuristics; they surface
  candidates for review rather than authoritative verdicts.
- PDF-from-URL is capped by the same 5 MB response limit as HTML.
- Quota accounting covers saved `sources/` and raw snapshots, not the user's
  pre-existing files in a linked folder.
