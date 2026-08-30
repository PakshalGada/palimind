# Universal Sans — font files

The UI uses **Universal Sans** (designed by Briton Smith / Family Type, the
typeface seen on Grok) via `@font-face`, with **Inter** as the automatic
fallback and **IBM Plex Mono** for code.

Universal Sans is a commercial typeface — place your licensed WOFF2 files in
this folder and they activate on the next build:

```
public/fonts/
├── UniversalSans-Text-400.woff2
├── UniversalSans-Text-400Italic.woff2
├── UniversalSans-Text-550.woff2
├── UniversalSans-Text-550Italic.woff2
├── UniversalSans-Display-400.woff2
└── UniversalSans-Display-550.woff2
```

If the files are missing the app renders in Inter — the CSS stack is
`"Universal Sans", "Inter", -apple-system, ...`, so nothing breaks.

License: purchase web/app licences from Family Type (universalsans.com).
Re-hosting xAI's own font files without a licence is not permitted.
