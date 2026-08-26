---
name: palimind-frontend
description: >
  React/TypeScript conventions for the Palimind UI. REQUIRED when editing
  packages/frontend. Triggers: React, Vite, component, hook, SSE, glance,
  chat UI, styling, tokens.
---

# Palimind Frontend

## Where things live

- App: `packages/frontend/` (React 19, TypeScript, Vite).
- `src/components/` — shared components (ChatArea, Sidebar, SettingsModal…).
- `src/views/` — top-level views (currently Agents.tsx).
- `src/glance/` — the separate Glance popup app (`glance.html` entry).
- `src/api.ts` — backend client; SSE streams are consumed inline today.

## Conventions

- TypeScript strict; build runs `tsc -b` — type errors break the build.
- Lint with oxlint (`npm run lint` inside packages/frontend).
- Styling is plain CSS files per component today; new design tokens will land
  in `src/styles/tokens.css` (see skills/brand when it exists). Prefer tokens
  over hard-coded colors for anything user-visible.
- Markdown rendering uses marked + katex with DOMPurify sanitization — never
  bypass the sanitizer for model output.
- Keep the Glance popup bundle small and independent of main-app state.
- Backend base URL is same-origin (`http://127.0.0.1:8000`) in dev; do not
  hardcode hosts in components.

## Commands

```
npm run dev   --prefix packages/frontend   # Vite dev server
npm run build --prefix packages/frontend   # tsc -b && vite build
npm run lint  --prefix packages/frontend   # oxlint
```

## Gotchas

- The desktop app loads `/ui` from the backend, not from Vite — test through
  the running backend (`make backend`, open http://127.0.0.1:8000/ui) or via
  Tauri dev.
