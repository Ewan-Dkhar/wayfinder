# Wayfinder — Technical Stack

## 1. System Architecture
Wayfinder follows a decoupled local client architecture: a lightweight Tauri v2 desktop HUD communicating with a high-throughput local Python engine daemon.

```
+--------------------------------------------------------+
|                 Desktop HUD (Tauri v2)                 |
|       - Solid.js / React + Tailwind CSS                |
|       - Native OS transparency & always-on-top         |
|       - Global shortcut listener (Alt + G, Esc)        |
+---------------------------+----------------------------+
                            | IPC / Local REST
+---------------------------v----------------------------+
|                    Local Daemon Engine                 |
|                                                        |
|  - Subtitle Fetcher / yt-dlp Audio Stream Ingestion    |
|  - Speech-to-Text: faster-whisper (CTranslate2, int8)  |
|  - Universal Game Store: SQLite FTS5 (BM25 search)     |
|  - Tactical SLM: Llama 3.2 3B-Instruct (4-bit quant)   |
|  - Structured Outputs: GBNF Grammar / Instructor       |
|  - Notification Dispatcher: Native OS toasts           |
+--------------------------------------------------------+
```

## 2. Component Technologies & Rationales
- **Tauri v2:** Idle memory footprint is < 35 MB, avoiding the 200MB+ resource overhead of Electron that competes with running games.
- **yt-dlp Subtitle Priority:** Pulls English caption tracks (`.vtt` / `.json3`) directly in under 1 second, bypassing heavy transcription when captions exist.
- **faster-whisper Fallback:** Runs quantized 8-bit Whisper on CPU/GPU only when raw audio must be transcribed.
- **SQLite FTS5:** Partitioned index enabling sub-10ms full-text keyword and semantic matching across thousands of transcript segments.
- **llama.cpp / Ollama (Llama 3.2 3B):** Generates 50-word tactical cards in ~600ms, adhering strictly to JSON schemas via grammar constraints.