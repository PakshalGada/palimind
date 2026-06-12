# -*- mode: python ; coding: utf-8 -*-
#
# palimind.spec — PyInstaller build spec for the Palimind sidecar binary
#
# Build command (from project root):
#   pyinstaller palimind.spec
#
# Output: dist/palimind-server/ (onedir mode — fast startup, no extraction)
#
# After build, rename the binary:
#   dist/palimind-server/palimind-server.exe
#   → src-tauri/binaries/palimind-server-x86_64-pc-windows-msvc.exe

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None

# ── Data files ──────────────────────────────────────────────────────────────────

# sentence-transformers models and config
datas = []
datas += collect_data_files("sentence_transformers")
datas += collect_data_files("transformers")
datas += collect_data_files("tokenizers")
datas += copy_metadata("sentence-transformers")
datas += copy_metadata("transformers")
datas += copy_metadata("tokenizers")
datas += copy_metadata("torch")

# Core prompt templates
datas += [("core/prompts", "core/prompts")]

# Frontend UI files (served by FastAPI)
datas += [("ui", "ui")]

# ── Hidden imports ───────────────────────────────────────────────────────────────

# Packages that PyInstaller misses due to dynamic imports
hidden_imports = [
    # FastAPI + Uvicorn
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "fastapi.staticfiles",
    "fastapi.middleware.cors",
    # Email crypto
    "cryptography",
    "cryptography.fernet",
    "cryptography.hazmat.primitives",
    "cryptography.hazmat.backends",
    # ML
    "sentence_transformers",
    "torch",
    "numpy",
    # Audio (lazy-loaded; included so they work on demand)
    "soundfile",
    "faster_whisper",
    "kokoro_onnx",
    # DB
    "turbovec",
    # Document parsers
    "pymupdf",
    "pptx",
    "openpyxl",
    "pandas",
    # Other
    "httpx",
    "watchdog",
    "watchdog.observers",
    "watchdog.events",
    "PIL",
    "pillow",
    "multipart",
    "anyio",
    "anyio._backends._asyncio",
    "starlette",
    "starlette.routing",
]

# Collect all sentence_transformers submodules
hidden_imports += collect_submodules("sentence_transformers")
hidden_imports += collect_submodules("transformers")

# ── Analysis ──────────────────────────────────────────────────────────────────────

a = Analysis(
    ["server_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=["config/pyinstaller/hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude things we definitely don't need
        "matplotlib",
        "scipy",
        "sklearn",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",     # We're replacing tkinter folder picker with Tauri dialog
        "_tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    exclude_binaries=False,
    name="palimind-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # Compress binaries (reduces size ~20%)
    console=True,           # Console app — logs are captured by Tauri
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="src-tauri/icons/icon.ico",  # Will be created in Tauri setup
)
