# PaliMind browser capture

Two ways to save the current page without opening the app:

1. **Browser extension** — load this folder as an unpacked extension
   (`chrome://extensions` → Developer mode → Load unpacked). Open the popup,
   paste the token from `~/.palimind/api_token`, save the connection, then use
   the toolbar button or the “Save page to PaliMind” context menu.
2. **Bookmarklet / share sheet** — use:

   ```
   http://127.0.0.1:8000/api/capture/link?token=<token>&url=<url>&title=<title>
   ```

   The endpoint saves into the active space, or pass `space_id=…`. Add
   `format=json` for scripts.

The extension only talks to the local PaliMind server (`127.0.0.1`/`localhost`).
