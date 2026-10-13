# Wayfinder — Project Directory Layout

```
wayfinder/
|-- docs/
|   |-- goal.md
|   |-- description.md
|   |-- tech_stack.md
|   |-- components.md
|   |-- project_structure.md
|   `-- agent_context.md
|
|-- core/                           # Local Python Engine Daemon
|   |-- ingestion/
|   |   |-- __init__.py
|   |   |-- parser.py               # yt-dlp subtitle & stream handler
|   |   |-- transcriber.py          # faster-whisper fallback worker
|   |   `-- chunker.py              # Transcript window segmentation
|   |-- db/
|   |   |-- __init__.py
|   |   |-- database.py             # SQLite setup & schema migration
|   |   |-- fts_engine.py           # Multi-game BM25 search queries
|   |   `-- seeds/
|   |       |-- sekiro_seed.py      # MVP initial boss pack
|   |       `-- wukong_seed.py      # Post-MVP seed pack
|   |-- llm/
|   |   |-- __init__.py
|   |   |-- client.py               # llama.cpp / Ollama bridge
|   |   |-- grammar.py              # GBNF grammar / Pydantic schemas
|   |   `-- prompts.py              # Universal tactical extraction prompt
|   |-- server.py                   # Local JSON-RPC / REST endpoint for HUD
|   `-- main.py                     # Backend daemon entrypoint
|
|-- desktop/                        # Tauri v2 Overlay Frontend
|   |-- src-tauri/
|   |   |-- Cargo.toml
|   |   |-- tauri.conf.json         # Transparency & shortcut settings
|   |   `-- src/
|   |       |-- main.rs             # Application setup & hotkey hooks
|   |       `-- toast.rs            # Native notifications
|   |-- src/
|   |   |-- components/
|   |   |   |-- OverlayHeader.tsx   # Active game pill + search bar
|   |   |   |-- TacticalCard.tsx    # Tell / Action / Outcome visual card
|   |   |   `-- GameSelector.tsx    # Switch active game library
|   |   |-- App.tsx
|   |   |-- index.css
|   |   `-- main.tsx
|   |-- package.json
|   `-- vite.config.ts
|
|-- scripts/
|   |-- index_video.py              # CLI tool: Ingest single YouTube URL into game DB
|   `-- dev.sh                      # Launch backend + Tauri HUD concurrently
|
|-- requirements.txt
`-- README.md
```