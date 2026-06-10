# Palimind Hotkey Feature

Global hotkey listener for capturing selected text and automatically saving it to Palimind Fields.

## Quick Start

### 1. Install Hotkey Dependencies

```bash
pip install -e ".[hotkey]"
```

This installs:
- `pynput` - Global hotkey registration
- `pyperclip` - Cross-platform clipboard access
- `requests` - HTTP API calls

### 2. Start the Hotkey Listener

```bash
pm hotkey start
```

The listener will start and wait for hotkey presses. Default hotkey is **Ctrl+Shift+E**.

### 3. Capture Text Anywhere

1. **Copy or select text** in any application (Ctrl+C or highlight)
2. **Press Ctrl+Shift+E** (the hotkey)
3. **A popup window appears** showing your available Fields
4. **Select the Field** to save to
5. **Text is automatically saved** to `field/.palimind/captures/` and indexed

### 4. Query Your Captures

Your captured text is automatically indexed and searchable through:
- The chat interface (Boardroom UI)
- `pm ask "query about your capture"`
- Any Field's search functionality

## CLI Usage

### Start with Default Hotkey

```bash
pm hotkey start
```

Listens on **Ctrl+Shift+E** (Windows, macOS, Linux).

### Custom Hotkey

```bash
pm hotkey start --hotkey "alt+shift+c"
```

Supported modifiers: `ctrl`, `shift`, `alt`, `cmd`

Examples:
- `ctrl+shift+e` - Control + Shift + E
- `alt+shift+c` - Alt + Shift + C
- `cmd+shift+d` - Command + Shift + D (macOS)

### Custom API Server

```bash
pm hotkey start --api-url http://192.168.1.100:8000
```

Useful if FastAPI server is on a different machine/port.

### Stop the Listener

Press **Ctrl+C** in the terminal to gracefully stop.

## Architecture

### Module Structure

```
hotkey/
├── __init__.py                # Module exports
├── models.py                  # Data classes (HotkeyConfig, HotkeyEvent, etc.)
├── platform_bindings.py       # Cross-platform hotkey + clipboard (pynput, pyperclip)
├── popup_ui.py               # Tkinter field selector window + field loader
├── manager.py                # Main orchestrator (hotkey → capture → popup → save)
└── integrations.py           # FastAPI client + file writer + processor
```

### Workflow

```
User presses hotkey (Ctrl+Shift+E)
         ↓
Platform bindings capture hotkey event
         ↓
Get selected text from clipboard
         ↓
Show field selector popup (tkinter)
         ↓
User selects target Field
         ↓
Save text as timestamped file to field/.palimind/captures/
         ↓
Trigger /api/update to re-index field
         ↓
Capture is now searchable in Field
```

### Data Storage

Captures are saved as:
```
my-field/
├── .palimind/
│   ├── config.json
│   ├── index.db
│   ├── captures/
│   │   ├── 2026-06-10_14-23-45_capture.txt
│   │   ├── 2026-06-10_14-25-12_capture.txt
│   │   └── ...
│   └── sessions.json
└── [other field files]
```

Captures are **automatically picked up** by the file indexer and **become searchable** in the Field's knowledge base.

## Platform Support

### Linux
- **Requirements**: `xclip`, `xsel`, or `wl-clipboard` for clipboard access
- **Install**: `sudo apt-get install xclip` (or `xsel`/`wl-clipboard`)
- **Hotkey**: Uses `pynput` keyboard listener (works with X11 and Wayland)

### macOS
- **Built-in**: Uses macOS native clipboard (`pbcopy`/`pbpaste`)
- **Hotkey**: Uses `pynput` keyboard listener

### Windows
- **Built-in**: Uses Windows native clipboard API
- **Hotkey**: Uses `pynput` keyboard listener

## Keyboard Modifiers

Supported modifiers across all platforms:
- `ctrl` - Control key
- `shift` - Shift key
- `alt` - Alt key (Windows/Linux) or Option key (macOS)
- `cmd` - Command key (macOS only)

Examples:
- `ctrl+shift+e` - Works on all platforms
- `cmd+shift+e` - macOS only
- `alt+shift+c` - Works on all platforms

## Error Handling

### Clipboard Not Available
If clipboard access fails (e.g., running in headless environment):
- Hotkey listener still runs
- Popup appears but has no text to save
- Can manually type text in popup (future enhancement)

### API Server Down
If FastAPI server is not running:
- Capture file is still saved locally
- Index update is skipped
- User sees warning message
- Capture will be indexed when server comes back up and `/api/update` is called manually

### Missing Dependencies
If optional dependencies are missing:
```
Error: Missing dependency: pynput not installed
Install with: pip install -e '.[hotkey]'
```

## Testing

### Run All Tests

```bash
python3 test_all_steps.py
```

Tests all 3 MVP steps:
1. Core infrastructure (hotkey + popup)
2. API integration & file saving
3. End-to-end workflow

### Run Individual Test Suites

```bash
# Test Step 1: Core infrastructure
python3 test_step1_hotkey.py

# Test Step 2: Capture & API integration
python3 test_step2_capture.py
```

## Demo Workflow

### 1. Start the UI and API Server

```bash
pm ui
```

Opens browser at `http://localhost:8000/ui/`

### 2. Create a Field

In the Boardroom UI:
- Click "Add Field"
- Select or create a directory
- Wait for indexing to complete

### 3. Start the Hotkey Listener

```bash
pm hotkey start
```

(In a separate terminal)

### 4. Capture Text

- Open a browser, document, or any text source
- Copy/highlight some text
- Press **Ctrl+Shift+E**
- Select the Field from popup
- Text is saved and indexed

### 5. Search Your Captures

In the Boardroom chat:
- Type a question about your captured text
- Palimind retrieves it from the captures directory
- Get AI-generated answer based on your capture

## Configuration

### Via CLI

```bash
pm hotkey start --hotkey "alt+shift+c" --api-url "http://localhost:8000"
```

### Programmatically

```python
from hotkey.manager import HotkeyManager, HotkeyConfig

config = HotkeyConfig(
    hotkey_combo="ctrl+shift+e",
    api_base_url="http://localhost:8000"
)
manager = HotkeyManager(config)

def on_event(event):
    print(f"Captured {len(event.selected_text)} chars to {event.selected_field.name}")

manager.start(on_event)
```

## Troubleshooting

### Hotkey Not Working

**Check 1**: Is the listener running?
```bash
pm hotkey start
```

**Check 2**: Is the correct hotkey being pressed?
Try the default `ctrl+shift+e` first.

**Check 3**: Does the application window have focus?
Global hotkeys should work in any window, but some applications may prevent it.

**Check 4**: Check if another application is using the same hotkey
Try a different hotkey combination: `--hotkey "alt+shift+c"`

### Clipboard Access Fails (Linux)

Install one of:
```bash
sudo apt-get install xclip      # X11
sudo apt-get install xsel       # X11
sudo apt-get install wl-clipboard  # Wayland
```

### API Connection Failed

Check if the API server is running:
```bash
pm ui  # Starts API server on port 8000
```

If on a different machine, specify the URL:
```bash
pm hotkey start --api-url "http://192.168.1.100:8000"
```

### Popup Window Doesn't Appear

**Check 1**: Are there any Fields? Create at least one in the UI first.

**Check 2**: Is tkinter installed? Usually comes with Python.
```bash
python3 -m tkinter  # Should open a small window
```

**Check 3**: Is the system running a display server (X11/Wayland)?
Popups may not work in headless environments.

## Future Enhancements

Possible improvements for post-MVP:
1. **Daemon mode** - Run hotkey listener as background service
2. **Hotkey management UI** - Configure hotkeys in Boardroom UI
3. **Capture preview** - Show captured text in popup before saving
4. **Multiple hotkeys** - Different hotkeys for different Fields
5. **Capture templates** - Save with metadata (source, tags, etc.)
6. **Headless mode** - Allow clipboard-only input without UI
7. **System tray** - Display hotkey listener status and controls
8. **Capture history** - Browse and manage recent captures
9. **OCR mode** - Capture screenshot and extract text
10. **Audio recording** - Record audio clips and save to Field

## Dependencies

### Required for Hotkey Feature

| Package | Purpose | Min Version |
|---------|---------|-------------|
| pynput | Global hotkey registration | 1.7.6 |
| pyperclip | Cross-platform clipboard | 1.9.0 |
| requests | HTTP API calls | 2.32.0 |

### Optional (Already in Palimind)

- `typer` - CLI framework (for `pm hotkey` command)
- `rich` - Formatted console output

## License

Part of Palimind project. Same license as main project.
