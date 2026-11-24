# Phase 11 — Hardening and release gate

Date: 2026-11-24

Scope: final hardening for the chat-first release. This document records the
checks, findings, fixes and residual risks. It is not a marketing overview.

## 1. Performance

### Bundle results after fixes

| Item | Before | After |
|---|---:|---:|
| Main JS | ~1.5 MB | ~740 KB |
| Main CSS | ~469 KB | ~309 KB |
| Frontend `dist` | ~12 MB | ~11 MB |

Fixes:

- Lazy-loaded secondary views and heavy modals with `React.lazy`/`Suspense`:
  Home, Knowledge, Projects, Artifacts, Agents, Settings, Agent Manager,
  Skill Manager, Knowledge Graph, Agent Graph, Plan Review, Research Plan,
  Task Monitor.
- Removed the client-side `pptxgenjs` fallback. PPTX export now always uses the
  local designed-deck backend pipeline. This removed duplicate rendering and
  the `image-size` dependency chain.
- Updated KaTeX to a compatible patched release (`0.18.10`).
- Moved `shadcn` to devDependencies because it is only used for build-time CSS.

### Runtime metrics

Measured with Playwright against the production preview build at 1440×900:

| Metric | Result |
|---|---:|
| DOMContentLoaded | ~88 ms |
| First paint | ~52 ms |
| First contentful paint | ~144 ms |
| DOM nodes on chat empty state | 488 |

These are local-machine numbers and should be treated as a regression baseline,
not a cross-device guarantee.

## 2. Responsive QA

Checked horizontal overflow (`documentElement.scrollWidth <= innerWidth`) at:

- 390 px
- 768 px
- 1024 px
- 1440 px

Surfaces:

- Chat
- Workbench (Artifacts, Browser, Files, Sources)
- Skill Manager
- Quick Ask
- Data Mode

Result: **no horizontal overflow** on any surface at any tested width.

## 3. Security review

### Dependency audit

`npm audit --omit=dev --prefix packages/frontend` now reports:

```
found 0 vulnerabilities
```

Fixes and rationale:

- Removed `pptxgenjs` client fallback and its vulnerable `image-size` chain.
- Updated KaTeX to a fixed version compatible with `marked-katex-extension`.
- Moved `shadcn` to devDependencies.
- A full `npm audit` still shows 4 moderate findings through
  `shadcn → ts-morph → minimatch`. These are build-time tooling only, are not
  shipped in the frontend bundle, and have no non-breaking fix at the current
  `shadcn` major.

### Backend security checks

Ran:

```bash
python -m pytest \
  tests/test_security_and_state.py \
  tests/test_tool_security.py \
  tests/test_uploads.py \
  tests/test_chat_bundle.py \
  tests/test_data_mode.py \
  tests/test_chat_audit.py -q
```

Result: **30 passed**.

Reviewed boundaries:

- API auth middleware: per-install bearer token, loopback/host guard, cookie
  session for the local UI.
- Uploads: path confinement under `~/.palimind/uploads`, size limits, MIME/kind
  detection.
- Data Mode: upload path must stay under the uploads folder; SQL must be a
  single read-only SELECT/WITH statement; writes are rejected.
- Chat bundles: filenames sanitized; contents are assembled in memory; stored
  under the app's exports folder.
- HTML/React artifacts render inside sandboxed iframes.
- Audit trails: chat/data/export actions and tool calls are recorded locally.
- Local-only guarantee: processing is local-first; remote access requires
  explicit configuration.

## 4. Multimodal verification

Previously, media skills referenced `image_ocr`, `audio_transcribe` and
`video_frames`, but the tools were not registered. This was a real gap and is
now fixed.

Added `palimind/agents/tools/media/tool.py` with:

- `image_info`
- `image_ocr` (local EasyOCR)
- `image_caption` (local vision model)
- `audio_transcribe` (local faster-whisper)
- `video_frames` (ffmpeg/ffprobe)

Verification:

- Tool registration test: all five tools are present in `get_tool_names()`.
- `image_info` reads real PNG dimensions/format.
- `image_ocr` plumbing test exercises the EasyOCR path with a stubbed extractor.
- `audio_transcribe` plumbing test exercises the faster-whisper path with a
  stubbed transcript.
- `video_frames` uses a generated 1-second MP4 and extracts real frames with
  ffmpeg.

Result: **5 passed** in `tests/test_media_tools.py`.

## 5. Accessibility

Cross-surface audit through the in-app checker and a Playwright DOM audit:

- Chat
- Workbench: Artifacts, Browser, Files, Sources
- Chat Details
- Memory
- Context Manager
- Share
- Intelligence
- Skill Manager
- Quick Ask
- Data Mode

Findings fixed during this pass:

- Attachment remove buttons had no accessible name.
- The Skill Manager “Build with AI” textarea had no accessible label.

Final result: **zero accessibility issues** in the audited DOM for every
surface above.

## 6. Release gate

| Gate | Status |
|---|---|
| Frontend production build | PASS |
| Frontend tests | PASS |
| Backend non-integration tests | PASS |
| Tauri `cargo check` | PASS |
| Runtime dependency audit | PASS (0 vulnerabilities) |
| Responsive QA | PASS |
| Accessibility audit | PASS |
| Multimodal tool paths | PASS |
| Release documentation | PASS |

## 7. Residual risks / known limitations

- Full `npm audit` still reports build-time-only moderate findings through the
  `shadcn` toolchain. No runtime exposure.
- OCR, speech recognition and vision captioning require optional local models
  and download/cache on first use.
- Video frame extraction requires `ffmpeg` and `ffprobe` on `PATH`.
- Prompt-injection detection is advisory, not a hard classifier. Files and
  pages are treated as data, not instructions.
- The global quick-ask hotkey can conflict with an existing window-manager
  binding on Linux; the tray menu provides a fallback.
- Runtime performance numbers are from the development machine and need
  cross-device confirmation before broad distribution.

## 8. Final verification snapshot

Commands run for this hardening cycle:

```bash
npm run build --prefix packages/frontend
npm test --prefix packages/frontend
cd packages/backend && python -m pytest -m "not integration"
cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml
npm audit --omit=dev --prefix packages/frontend
```

Results:

- Frontend build: PASS
- Frontend tests: 189 passed, render smoke OK
- Backend tests: 913 passed, 2 skipped, 7 deselected
- Tauri `cargo check`: PASS
- Runtime dependency audit: 0 vulnerabilities
- Main JS bundle: ~740 KB; main CSS: ~309 KB; `dist`: ~11 MB
- Responsive QA: no horizontal overflow at 390/768/1024/1440 px
- Accessibility audit: zero issues across all audited surfaces
- Multimodal tools: 5 media-tool tests passed, including real ffmpeg frame extraction
