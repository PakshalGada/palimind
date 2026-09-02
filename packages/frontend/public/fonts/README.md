# Fonts

The UI uses **Universal Sans** (designed by Briton Smith / Family Type) for body
text, headings, and UI labels, **Space Grotesk** (SIL OFL) for the Palimind
logo/wordmark, and **IBM Plex Mono** (SIL OFL) for code and monospace elements.

## Bundled (open source)

Downloaded from Google Fonts:

```
public/fonts/
├── IBMPlexMono-400.woff2       # Code — Regular / 400
├── IBMPlexMono-400Italic.woff2 # Code — Regular italic / 400
├── SpaceGrotesk-var.woff2      # Logo/wordmark — variable 300–700 (latin subset)
└── NotoSerif-400Italic.woff2   # Legacy serif fallback — italic / 400
```

## Universal Sans (bring your licensed files)

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
