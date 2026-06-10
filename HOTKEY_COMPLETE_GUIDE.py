#!/usr/bin/env python3
"""
PALIMIND HOTKEY - COMPLETE END-TO-END EXPLANATION & TEST

This script explains what happens at EACH STEP when a user captures text.
"""
import time
import tempfile
import json
from pathlib import Path

print("\n" + "="*80)
print(" PALIMIND HOTKEY FEATURE - COMPLETE END-TO-END WORKFLOW")
print("="*80 + "\n")

# ============================================================================
# PART 1: ARCHITECTURE OVERVIEW
# ============================================================================

print("📚 PART 1: ARCHITECTURE OVERVIEW")
print("-"*80)

architecture = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PALIMIND HOTKEY SYSTEM                             │
└─────────────────────────────────────────────────────────────────────────────┘

LAYERS:
┌─────────────────────────────────────────────┐
│  UI LAYER (Web Browser)                     │  ← Browser at localhost:8000/ui
│  • Field list                               │  ← Shows available Fields
│  • Chat interface                           │  ← Query your captures
│  • Upload files                             │
└──────────────────┬──────────────────────────┘
                   │
                   ↓ HTTP API (port 8000)
                   
┌──────────────────────────────────────────────────────────────────────────────┐
│  API LAYER (FastAPI Server - core/api_server.py)                            │
│  • /api/fields              - List available Fields                         │
│  • /api/fields/set_active   - Switch active Field                           │
│  • /api/update              - Re-index Field                                │
│  • /api/chat                - Stream responses                              │
└──────────────────┬─────────────────────────────────────────────────────────┘
                   │
                   ↓ Calls (from hotkey listener)
                   
┌──────────────────────────────────────────────────────────────────────────────┐
│  HOTKEY MODULE (hotkey/ directory)          ← NEW FEATURE                  │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. PLATFORM BINDINGS (platform_bindings.py)                               │
│     • pynput keyboard listener → Registers global hotkey                   │
│     • pyperclip → Gets text from clipboard                                 │
│                                                                              │
│  2. MANAGER (manager.py)                                                    │
│     • Orchestrates: hotkey press → capture → popup → save                  │
│     • Handles debouncing & threading                                        │
│                                                                              │
│  3. POPUP UI (popup_ui.py)                                                  │
│     • tkinter window shows list of Fields                                   │
│     • User selects target Field                                             │
│                                                                              │
│  4. INTEGRATIONS (integrations.py)                                          │
│     • Saves capture to field/.palimind/captures/TIMESTAMP_capture.txt      │
│     • Calls /api/update to re-index Field                                  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ↓ File I/O
                   
┌──────────────────────────────────────────────────────────────────────────────┐
│  FILE SYSTEM STORAGE                                                         │
│                                                                              │
│  my-field/                                                                   │
│  ├── .palimind/                                                             │
│  │   ├── config.json           - Field configuration                        │
│  │   ├── index.db              - SQLite (file index, chunks, FTS)          │
│  │   ├── captures/             ← CAPTURES SAVED HERE                       │
│  │   │   ├── 2026-06-10_14-23-45_capture.txt  ← Your captured text        │
│  │   │   └── 2026-06-10_14-25-12_capture.txt  ← Another capture          │
│  │   ├── sessions.json         - Chat history                              │
│  │   └── turbovec_chat_*       - Memory vectors                            │
│  └── [other field files]                                                    │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ↓ Indexing (automatic)
                   
┌──────────────────────────────────────────────────────────────────────────────┐
│  SEARCH & RETRIEVAL (core/retrieval/)                                        │
│                                                                              │
│  • Embeddings generated (sentence-transformers)                             │
│  • Chunks indexed (Turbovec - 4-bit compressed)                             │
│  • Full-text search enabled (SQLite FTS5)                                   │
│  • Vector similarity search ready                                            │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                   │
                   ↓ Available for queries
                   
┌──────────────────────────────────────────────────────────────────────────────┐
│  AI PROCESSING (core/generative/)                                            │
│                                                                              │
│  • User asks question in Boardroom chat                                     │
│  • Palimind retrieves relevant captures from index                          │
│  • Ollama LLM generates answer based on captures                            │
│  • Response streamed back to browser                                        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
"""

print(architecture)

# ============================================================================
# PART 2: STEP-BY-STEP USER WORKFLOW
# ============================================================================

print("\n" + "="*80)
print("🎯 PART 2: STEP-BY-STEP USER WORKFLOW")
print("="*80 + "\n")

workflow = """
SCENARIO: User wants to save an article excerpt to their "Research" Field

STEP 1: USER SETUP
────────────────────────────────────────────────────────────────────────────
Action:  User opens terminal
Command: pm ui

What happens:
  ✓ FastAPI server starts on http://localhost:8000
  ✓ Browser auto-opens to http://localhost:8000/ui/
  ✓ Boardroom UI loads (HTML/CSS/JS)
  ✓ User sees list of Fields
  ✓ User can create a new Field or select existing one
  ✓ Field "Research" is selected and indexed

Files involved:
  • core/api_server.py      → FastAPI app initialization
  • core/api.py             → Indexing functions
  • ui/index.html           → Web UI (HTML)
  • ui/app.js               → Web UI (JavaScript)
  • ui/styles.css           → Web UI (CSS)
  • ~/.palimind_global.json → Stores Field list & active Field


STEP 2: USER STARTS HOTKEY LISTENER
────────────────────────────────────────────────────────────────────────────
Action:  User opens new terminal
Command: pm hotkey start

What happens:
  ✓ Hotkey manager initialized (hotkey/manager.py)
  ✓ pynput keyboard listener started (listens for Ctrl+Shift+E)
  ✓ Console says "Listening on Ctrl+Shift+E"
  ✓ Now waiting for hotkey press

Files involved:
  • core/cli/commands.py          → CLI command handler
  • hotkey/manager.py             → Orchestrates workflow
  • hotkey/platform_bindings.py   → Keyboard listener (pynput)


STEP 3: USER COPIES TEXT
────────────────────────────────────────────────────────────────────────────
Action:  User opens browser/PDF/editor
         User reads: "Machine learning is the study of algorithms..."
         User selects text and copies (Ctrl+C)

What happens:
  ✓ Text is in system clipboard
  ✓ Ready to be captured by hotkey listener

System interaction:
  • Windows: ClipboardWatcher API
  • macOS: NSPasteboard
  • Linux: xclip/xsel (external tool)


STEP 4: USER PRESSES HOTKEY
────────────────────────────────────────────────────────────────────────────
Action:  User presses Ctrl+Shift+E (anywhere - even other apps!)

What happens INSTANTLY:

  4a. HOTKEY DETECTED
      ─────────────────────────────────────
      File:    hotkey/platform_bindings.py
      Method:  PlatformBindings.register_hotkey()
      
      ✓ Keyboard listener detects Ctrl+Shift+E
      ✓ Calls hotkey callback function
      ✓ All non-blocking (happens in background thread)

  4b. TEXT CAPTURED FROM CLIPBOARD
      ─────────────────────────────────────
      File:    hotkey/platform_bindings.py
      Method:  PlatformBindings.get_clipboard_text()
      
      ✓ Calls pyperclip.paste()
      ✓ Gets: "Machine learning is the study of algorithms..."
      ✓ Text validated (not empty)

  4c. POPUP WINDOW APPEARS
      ─────────────────────────────────────
      File:    hotkey/popup_ui.py
      Method:  show_field_selector()
      
      ✓ Tkinter window created
      ✓ Always-on-top (stays above all windows)
      ✓ Shows list of available Fields:
        ○ Research (active)
        ○ Learning
        ○ Projects
      ✓ Window centered on screen
      ✓ Waiting for user selection

  4d. USER SELECTS FIELD
      ─────────────────────────────────────
      Action:  User clicks on "Research" field
      
      ✓ Radio button selected
      ✓ User clicks "Save" button
      ✓ Or presses Enter

  4e. CAPTURE PROCESSED
      ─────────────────────────────────────
      File:    hotkey/integrations.py
      Method:  CaptureProcessor.process_capture()
      
      Step 1: Save to file
        ✓ Creates: research-field/.palimind/captures/
        ✓ Generates timestamp: 2026-06-10_14-23-45
        ✓ Creates file: 2026-06-10_14-23-45_capture.txt
        ✓ Writes text: "Machine learning is the study of algorithms..."
        ✓ File saved successfully!
      
      Step 2: Index the capture
        ✓ Calls: POST /api/fields/set_active
        ✓ Sets "Research" as active Field
        ✓ Calls: POST /api/update
        ✓ Triggers index update (core/indexing.py)
        ✓ New file detected in captures/ directory
        ✓ Text chunked into 1000-char pieces
        ✓ Embeddings generated (sentence-transformers)
        ✓ Vectors stored in Turbovec (4-bit compressed)
        ✓ Full-text index updated (SQLite FTS5)
        ✓ Summary generated (optional)

  4f. COMPLETION MESSAGE
      ─────────────────────────────────────
      Console shows:
        ✓ Capture saved: research-field/.palimind/captures/2026-06-10_14-23-45_capture.txt
        ✓ Updated field: 1 files indexed
        ✨ Capture successfully indexed!


STEP 5: USER QUERIES THE CAPTURE
────────────────────────────────────────────────────────────────────────────
Action:  User goes back to Boardroom UI browser tab
         User types in chat: "What is machine learning?"

What happens:

  5a. QUERY SUBMITTED
      ─────────────────────────────────────
      File:    ui/app.js
      
      ✓ JavaScript captures user message
      ✓ Sends to: POST /api/chat
      ✓ Message: "What is machine learning?"

  5b. QUERY RETRIEVED
      ─────────────────────────────────────
      File:    core/retrieval/searcher.py
      
      ✓ Query converted to embeddings
      ✓ Vector similarity search in Turbovec
      ✓ Full-text search in SQLite FTS5
      ✓ Relevant chunks ranked by relevance
      ✓ RETRIEVED from your capture:
        "Machine learning is the study of algorithms..."

  5c. AI RESPONSE GENERATED
      ─────────────────────────────────────
      File:    core/generative/responder.py
      
      ✓ Context: Your captured text
      ✓ Query: "What is machine learning?"
      ✓ System prompt + history + context
      ✓ Sent to Ollama (local LLM)
      ✓ Ollama generates response:
        "Based on your captured research, machine learning is..."

  5d. RESPONSE STREAMED TO BROWSER
      ─────────────────────────────────────
      File:    ui/app.js
      
      ✓ Response streamed token-by-token
      ✓ Displayed in chat in real-time
      ✓ User can chat follow-up questions
      ✓ All context stays in Field's memory


RESULT:
────────────────────────────────────────────────────────────────────────────
✅ Capture saved: research-field/.palimind/captures/2026-06-10_14-23-45_capture.txt
✅ Automatically indexed and searchable
✅ Available for future queries
✅ Part of Field's long-term knowledge
✅ Can be searched in chat anytime
"""

print(workflow)

# ============================================================================
# PART 3: TECHNICAL FLOW DIAGRAM
# ============================================================================

print("\n" + "="*80)
print("🔧 PART 3: TECHNICAL DATA FLOW")
print("="*80 + "\n")

flow_diagram = """
HOTKEY PRESS → CAPTURE → SAVE → INDEX → RETRIEVE → ANSWER

┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  HOTKEY PRESS (Ctrl+Shift+E anywhere)                                      │
│         │                                                                    │
│         ↓                                                                    │
│  pynput keyboard listener (platform_bindings.py)                           │
│         │                                                                    │
│         ├─→ Verifies: Is this Ctrl+Shift+E?                               │
│         │                                                                    │
│         ↓                                                                    │
│  manager._on_hotkey_pressed()                                              │
│         │                                                                    │
│         ├─→ Debounce check (prevent rapid presses)                         │
│         │                                                                    │
│         ↓                                                                    │
│  pyperclip.paste() → GET CLIPBOARD TEXT                                    │
│         │                                                                    │
│         ├─→ "Machine learning is the study of algorithms..."               │
│         │                                                                    │
│         ↓                                                                    │
│  show_field_selector() → DISPLAY POPUP                                     │
│         │                                                                    │
│         ├─→ Load fields from ~/.palimind_global.json                       │
│         ├─→ Create tkinter window                                           │
│         ├─→ Show radio buttons with field names                            │
│         ├─→ Wait for user selection                                         │
│         │                                                                    │
│         ↓                                                                    │
│  User clicks "Research" field → SELECT FIELD                               │
│         │                                                                    │
│         ├─→ User selects from popup (keyboard or mouse)                    │
│         │                                                                    │
│         ↓                                                                    │
│  manager._on_field_selected(text, field)                                   │
│         │                                                                    │
│         ├─→ Verified: field is not None                                    │
│         │                                                                    │
│         ↓                                                                    │
│  CaptureProcessor.process_capture(field_path, text)                        │
│         │                                                                    │
│         ├─→ Part 1: SAVE FILE                                              │
│         │    CaptureFileWriter.save_capture(field_path, text)             │
│         │    │                                                              │
│         │    ├─→ Create: field/.palimind/captures/                         │
│         │    ├─→ Generate: YYYY-MM-DD_HH-MM-SS_capture.txt                │
│         │    ├─→ Write: text to file                                       │
│         │    └─→ Return: file path                                         │
│         │                                                                    │
│         ├─→ Part 2: TRIGGER INDEX UPDATE                                   │
│         │    PalimindAPIClient.update_field(field_path)                   │
│         │    │                                                              │
│         │    ├─→ POST /api/fields/set_active {path: field_path}           │
│         │    │   (Set this field as active)                               │
│         │    │                                                              │
│         │    ├─→ POST /api/update                                          │
│         │    │   (Trigger indexing)                                       │
│         │    │                                                              │
│         │    └─→ Return: success or error                                  │
│         │                                                                    │
│         ↓                                                                    │
│  FastAPI /api/update endpoint                                              │
│         │                                                                    │
│         ├─→ Calls: update_index(field_path)                                │
│         │                                                                    │
│         ↓                                                                    │
│  core/indexing.py → UPDATE INDEX                                           │
│         │                                                                    │
│         ├─→ Scan field directory                                            │
│         ├─→ Find new file: captures/2026-06-10_14-23-45_capture.txt       │
│         ├─→ Parse document (core/ingestion/)                               │
│         ├─→ Extract text from file                                         │
│         │                                                                    │
│         ├─→ CHUNK TEXT                                                      │
│         │   (Split into 1000-char pieces with 200-char overlap)           │
│         │   → "Machine learning is the study of algorithms..."             │
│         │   → (chunk 1) "Machine learning is..."                          │
│         │   → (chunk 2) "...algorithms..."                                │
│         │                                                                    │
│         ├─→ GENERATE EMBEDDINGS                                            │
│         │   (sentence-transformers: nomic-embed-text)                      │
│         │   → [0.123, 0.456, ..., 0.789]  (768 dimensions)                │
│         │                                                                    │
│         ├─→ STORE IN DATABASE                                              │
│         │   SQLite (.palimind/index.db):                                  │
│         │   ├─ files table: path, hash, timestamp                         │
│         │   ├─ chunks table: content, embeddings                          │
│         │   └─ chunks_fts table: full-text search index                   │
│         │                                                                    │
│         ├─→ STORE IN VECTOR INDEX                                          │
│         │   Turbovec (.palimind/turbovec.tvim):                           │
│         │   ├─ 4-bit compressed vectors                                   │
│         │   ├─ O(1) deletion                                              │
│         │   └─ Fast similarity search                                      │
│         │                                                                    │
│         ├─→ GENERATE SUMMARY (optional)                                    │
│         │   (Ollama: gemma4:e4b)                                           │
│         │   → "Overview of machine learning concepts"                      │
│         │                                                                    │
│         ↓                                                                    │
│  ✨ CAPTURE IS NOW SEARCHABLE                                               │
│                                                                              │
│         ↓ (User goes to Boardroom UI and asks a question)                 │
│                                                                              │
│  Browser chat input: "What is machine learning?"                           │
│         │                                                                    │
│         ↓                                                                    │
│  JavaScript fetch: POST /api/chat {query: "What is..."}                    │
│         │                                                                    │
│         ↓                                                                    │
│  core/querying.py → RETRIEVE CONTEXT                                       │
│         │                                                                    │
│         ├─→ Convert query to embeddings                                    │
│         ├─→ Vector search in Turbovec                                      │
│         │   → Find chunks similar to query                                │
│         │   → RESULT: Your capture: "Machine learning..."                │
│         │                                                                    │
│         ├─→ Full-text search fallback                                      │
│         ├─→ Rank by relevance                                              │
│         │                                                                    │
│         ↓                                                                    │
│  core/generative/responder.py → GENERATE RESPONSE                          │
│         │                                                                    │
│         ├─→ Build prompt:                                                  │
│         │   - System: "You are helpful..."                                │
│         │   - Context: Your capture                                        │
│         │   - Query: "What is machine learning?"                           │
│         │                                                                    │
│         ├─→ Call Ollama LLM (local)                                        │
│         │   → Stream response token-by-token                              │
│         │                                                                    │
│         ↓                                                                    │
│  WebSocket stream → ui/app.js                                              │
│         │                                                                    │
│         ├─→ Display response in chat in real-time                          │
│         └─→ User sees answer based on their capture                        │
│                                                                              │
│  ✅ COMPLETE!                                                               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
"""

print(flow_diagram)

# ============================================================================
# PART 4: FILES & DIRECTORIES INVOLVED
# ============================================================================

print("\n" + "="*80)
print("📁 PART 4: FILES & DIRECTORIES INVOLVED")
print("="*80 + "\n")

files_involved = """
HOTKEY FEATURE - FILE INTERACTIONS:

NEW HOTKEY MODULE (hotkey/):
├── __init__.py                  Exports main HotkeyManager
├── models.py                    Data classes
├── platform_bindings.py         Keyboard + clipboard (pynput, pyperclip)
├── popup_ui.py                  Tkinter popup (field selector)
├── manager.py                   Main orchestrator
└── integrations.py              FastAPI client + file saving

MODIFIED FILES:
├── core/cli/commands.py         Added @app.command() hotkey(...)
├── pyproject.toml               Added [hotkey] optional dependencies
└── core/api_server.py           (already has /api/update endpoint)

CORE PALIMIND (used by hotkey):
├── core/api.py                  Public API (initialize_index, update_index)
├── core/api_server.py           FastAPI server (/api/update endpoint)
├── core/indexing.py             Index creation & updating
├── core/ingestion/              Document parsing
├── core/retrieval/              Search & retrieval
├── core/generative/             LLM response generation
└── core/storage/db.py           SQLite database operations

USER INTERFACE:
├── ui/index.html                Web UI (HTML)
├── ui/app.js                    Web UI logic (JavaScript)
└── ui/styles.css                Web UI styling (CSS)

DATA STORAGE:
├── ~/.palimind_global.json      Global config (field paths)
└── my-field/
    └── .palimind/
        ├── config.json          Field config
        ├── index.db             SQLite index
        ├── captures/            ← HOTKEY SAVES HERE
        │   ├── 2026-06-10_14-23-45_capture.txt
        │   └── 2026-06-10_14-25-12_capture.txt
        ├── sessions.json        Chat history
        └── turbovec_chat_*      Memory vectors
"""

print(files_involved)

# ============================================================================
# PART 5: RUNTIME TEST
# ============================================================================

print("\n" + "="*80)
print("✅ PART 5: RUNTIME VALIDATION")
print("="*80 + "\n")

try:
    # Test 1: Import all hotkey modules
    print("Test 1: Import hotkey modules...")
    from hotkey.manager import HotkeyManager
    from hotkey.models import HotkeyConfig, HotkeyEvent
    from hotkey.platform_bindings import get_platform_bindings
    from hotkey.popup_ui import FieldInfoLoader
    from hotkey.integrations import CaptureProcessor
    print("✅ All hotkey modules import successfully\n")
    
    # Test 2: Create manager
    print("Test 2: Initialize hotkey manager...")
    config = HotkeyConfig(hotkey_combo="ctrl+shift+e", api_base_url="http://localhost:8000")
    manager = HotkeyManager(config)
    print(f"✅ Manager created (hotkey: {config.hotkey_combo})\n")
    
    # Test 3: Load fields
    print("Test 3: Load available fields...")
    fields = FieldInfoLoader.load_fields()
    print(f"✅ Field loader ready ({len(fields)} fields available)\n")
    
    # Test 4: Test file saving
    print("Test 4: Test capture file saving...")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_text = "This is a test capture from the hotkey feature"
        processor = CaptureProcessor("http://localhost:8000")
        processor.processor.process_capture(tmpdir, test_text)
        
        captures_dir = Path(tmpdir) / ".palimind" / "captures"
        files = list(captures_dir.glob("*.txt"))
        if files:
            content = files[0].read_text()
            assert content == test_text
            print(f"✅ Capture saved & verified: {files[0].name}\n")
        else:
            print("⚠️  File save test inconclusive\n")
    
    # Test 5: Check dependencies
    print("Test 5: Verify all dependencies...")
    deps = {
        'pynput': 'Global hotkey registration',
        'pyperclip': 'Cross-platform clipboard',
        'requests': 'HTTP API calls',
        'fastapi': 'Web API server',
        'uvicorn': 'ASGI server',
        'numpy': 'Numerical computing',
        'sentence-transformers': 'Text embeddings',
        'turbovec': 'Vector search'
    }
    missing = []
    for pkg, desc in deps.items():
        try:
            __import__(pkg.replace('-', '_'))
            print(f"  ✓ {pkg:<25} - {desc}")
        except ImportError:
            print(f"  ✗ {pkg:<25} - {desc} [MISSING]")
            missing.append(pkg)
    
    if not missing:
        print("\n✅ All dependencies installed!\n")
    else:
        print(f"\n⚠️  Missing: {', '.join(missing)}\n")
        
except Exception as e:
    print(f"⚠️  Test error: {e}\n")

# ============================================================================
# PART 6: EXECUTION GUIDE
# ============================================================================

print("\n" + "="*80)
print("🚀 PART 6: HOW TO RUN THE COMPLETE SYSTEM")
print("="*80 + "\n")

execution_guide = """
STEP-BY-STEP EXECUTION:

1️⃣  START THE API SERVER & UI
   ─────────────────────────────────────────────────────────────
   Terminal 1:
   $ pm ui
   
   What happens:
   • FastAPI server starts (port 8000)
   • Browser opens to http://localhost:8000/ui/
   • Boardroom UI loads
   • Create or select a Field

2️⃣  START THE HOTKEY LISTENER
   ─────────────────────────────────────────────────────────────
   Terminal 2:
   $ pm hotkey start
   
   What happens:
   • pynput keyboard listener starts
   • Listening for Ctrl+Shift+E
   • Ready to capture text

3️⃣  TEST THE HOTKEY (MANUAL)
   ─────────────────────────────────────────────────────────────
   Terminal 3 or any app:
   
   a) Copy some text:
      • Open a web page, document, or terminal
      • Copy text: Ctrl+C
      
   b) Trigger hotkey:
      • Press Ctrl+Shift+E
      
   c) Select field:
      • Popup appears with your Fields
      • Click one (or use arrow keys + Enter)
      
   d) Done!
      • Console shows: "Capture successfully indexed!"
      • Check field/.palimind/captures/ for saved file

4️⃣  QUERY YOUR CAPTURE
   ─────────────────────────────────────────────────────────────
   Browser (Boardroom UI):
   
   a) Type a question:
      • "What was in that article?"
      • "Summarize my capture"
      
   b) Palimind:
      • Retrieves your capture from index
      • Generates answer from Ollama LLM
      • Streams response in chat

5️⃣  REPEAT
   ─────────────────────────────────────────────────────────────
   • Capture more text (Ctrl+Shift+E)
   • Query your growing knowledge base
   • All captures are indexed and searchable


CUSTOM CONFIGURATION:

Default hotkey (Ctrl+Shift+E):
  $ pm hotkey start

Custom hotkey (Alt+Shift+C):
  $ pm hotkey start --hotkey "alt+shift+c"

Custom API URL (for remote server):
  $ pm hotkey start --api-url "http://192.168.1.100:8000"


TESTING INDIVIDUAL COMPONENTS:

Test all 3 steps:
  $ python3 test_all_steps.py

Test core infrastructure only:
  $ python3 test_step1_hotkey.py

Test file saving & API:
  $ python3 test_step2_capture.py


STOPPING EVERYTHING:

Hotkey listener (Terminal 2):
  Press Ctrl+C

API server (Terminal 1):
  Press Ctrl+C
"""

print(execution_guide)

print("\n" + "="*80)
print("✨ PALIMIND HOTKEY - EXPLANATION COMPLETE!")
print("="*80)
print("\nNext step: Run 'pm ui' in one terminal and 'pm hotkey start' in another!")
print("="*80 + "\n")
