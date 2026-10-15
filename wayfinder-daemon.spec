# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification file for Wayfinder micro-daemon.

Bundles FastAPI, SQLite WAL FTS5 engine, dynamic uvicorn protocols,
yt-dlp extractors, and faster-whisper CTranslate2 native binaries
into a single self-contained executable for Tauri sidecar distribution.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all dynamic submodules, binaries, and data for complex packages
yt_dlp_datas, yt_dlp_binaries, yt_dlp_hidden = collect_all("yt_dlp")
whisper_datas, whisper_binaries, whisper_hidden = collect_all("faster_whisper")
ctranslate_datas, ctranslate_binaries, ctranslate_hidden = collect_all("ctranslate2")

# Combine all datas
datas = [
    ("wayfinder.db", "."),
] + yt_dlp_datas + whisper_datas + ctranslate_datas

# Combine all binaries
binaries = yt_dlp_binaries + whisper_binaries + ctranslate_binaries

# Explicit hidden imports for dynamic imports invisible to static AST
hiddenimports = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "anyio._backends._asyncio",
    "pydantic",
    "pydantic_core",
    "sqlite3",
    "httpx",
    "fastapi",
    "starlette",
    "core.config",
    "core.db.database",
    "core.db.fts_engine",
    "core.llm.client",
    "core.llm.synthesizer",
    "core.llm.prompts",
    "core.llm.schemas",
    "core.ingestion.chunker",
    "core.ingestion.steam_parser",
    "core.ingestion.yt_parser",
    "core.ingestion.transcriber",
] + yt_dlp_hidden + whisper_hidden + ctranslate_hidden

a = Analysis(
    ["core/server.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "notebook", "scipy"],
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
    [],
    name="wayfinder-daemon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
