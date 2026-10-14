# Wayfinder — Architectural Decision Log & Project Roadmap

This document serves as the permanent record of all architectural decisions, design trade-offs, current engineering state, and the forward plan for **Wayfinder**.

---

## 1. Executive Summary & Core Identity

**Wayfinder** is a local-first in-game companion HUD designed to synthesize 3-bullet tactical cheat sheets on demand while games are running.

### The Bedrock-First Philosophy
Rather than starting with a flashy UI overlay, Wayfinder is engineered from the bedrock up:
1. **Bedrock:** Sub-millisecond local data retrieval without network or AI inference.
2. **Engine:** Fast, local, grammar-constrained SLM extraction.
3. **Pipeline:** Automated ingestion of YouTube transcripts and Steam guides.
4. **Interface:** Non-intrusive, transparent Tauri v2 overlay.
5. **Validation:** Stress testing against active games with zero dropped frames.

---

## 2. Architectural Decision Records (ADRs)

### ADR-001: SQLite FTS5 BM25 over Vector Embeddings (RAG)
* **Date:** Phase 1
* **Context:** Modern AI systems default to vector databases (Chroma, FAISS, pgvector) with cosine similarity.
* **Decision:** Use SQLite's native `FTS5` virtual table with Okapi BM25 ranking.
* **Rationale:** 
  1. *Latency:* Vector embedding models introduce 50–200ms cold-start and inference overhead. SQLite FTS5 executes in **0.15ms**.
  2. *Precision:* Gaming queries involve exact proper nouns and mechanics (*"lightning reversal"*, *"Mikiri counter"*, *"terror roar"*). BM25 lexically matches exact terms with near-zero false positives.
  3. *Compute Isolation:* Zero GPU memory overhead; SQLite runs strictly in-process using standard C libraries.

---

### ADR-002: External Content Table with Automated Triggers
* **Date:** Phase 1
* **Context:** FTS5 can store its own copy of indexed text, which duplicates database size on disk.
* **Decision:** Declare `guide_fts` as an external content table (`content='guide_chunks', content_rowid='id'`) synchronized via 3 SQL triggers (`AFTER INSERT`, `AFTER DELETE`, `AFTER UPDATE`).
* **Rationale:** Eliminates data duplication while ensuring that application code only writes to `guide_chunks`. Index synchronization is atomic and engine-enforced.

---

### ADR-003: SQLite WAL Mode & 64MB In-Memory Cache
* **Date:** Phase 1
* **Context:** Database reads must not block background writes and must execute within single-digit milliseconds.
* **Decision:** Enforce `PRAGMA journal_mode = WAL;`, `PRAGMA synchronous = NORMAL;`, `PRAGMA cache_size = -64000;`, and `PRAGMA temp_store = MEMORY;` on all connections.
* **Rationale:** Readers never block writers. The 64MB cache ensures that the entire active game combat index resides in L3 cache/RAM, reducing disk I/O to zero during combat queries.

---

### ADR-004: FTS5 Stop-Word Stripping and OR Disjunction
* **Date:** Phase 2
* **Context:** SQLite FTS5 interprets space-separated words as an implicit `AND`. When players ask natural language questions (*"How to counter Genichiro lightning"*), queries failed because transcripts do not contain conversational filler like *"How to"*.
* **Decision:** Strip conversational stop words in [`sanitize_query`](file:///home/ewan/Projects/wayfinder/core/db/fts_engine.py#L67) and join content tokens with `OR`.
* **Rationale:** BM25 naturally sums IDF scores of all matched terms. Documents with high term overlap rank highest, but searches never fail due to missing conversational filler.

---

### ADR-005: Multi-Source Ingestion (YouTube Transcripts + Steam / Wiki Guides)
* **Date:** Phase 1 Upgrade & Phase 3
* **Context:** Spoken YouTube transcripts have rich timing data but contain audio ASR misspellings and creator fluff. Written Steam Community Guides have 100% exact terminology and structured bullets, but lack video timestamps.
* **Decision:** Extend the schema to be source-agnostic with `source_type` (`'youtube'`, `'steam'`, `'wiki'`) and `source_ref`.
* **Rationale:** Enables a tiered retrieval hierarchy: players get pristine spelling and concise bullet points from Steam guides when available, while retaining exact video clip timestamps from YouTube.

---

### ADR-006: Local SLM (Llama-3.2-3B Q4_K_M) with Grammar Masking over Cloud APIs
* **Date:** Phase 2
* **Context:** Cloud APIs (OpenAI, Gemini) introduce 1–3s network latency and fail offline. Large local models (7B/14B) consume 5GB+ VRAM, competing with active 3D games on an 8GB GPU.
* **Decision:** Target a 4-bit quantized 3B model (`Llama-3.2-3B-Instruct` Q4_K_M) via Ollama with `format: "json"`.
* **Rationale:** Consumes only ~2.0 GB VRAM and generates ~60 tokens in under 1.5s on an RTX 4060. Grammar masking forces the token sampler to output 100% syntactically valid JSON.

---

### ADR-007: Pydantic v2 Schema Enforcement for TacticalCard
* **Date:** Phase 2
* **Context:** Frontend HUD overlays require strict, guaranteed data shapes to render without `undefined` runtime exceptions.
* **Decision:** Define [`TacticalCard`](file:///home/ewan/Projects/wayfinder/core/llm/schemas.py#L35) and [`TacticalCue`](file:///home/ewan/Projects/wayfinder/core/llm/schemas.py#L14) using Pydantic v2.
* **Rationale:** Enforces the universal combat loop (`tell` $\rightarrow$ `action` $\rightarrow$ `outcome`), caps summaries at 25 words for glanceability, and validates in under 0.03ms via Rust `pydantic-core`.

---

### ADR-008: 3-Tier Defensive Parsing and Zero-Crash Fallback Synthesizer
* **Date:** Phase 2
* **Context:** If local inference times out or produces slight formatting irregularities under heavy GPU gaming load, an unhandled exception will crash the game overlay.
* **Decision:** Implement a 3-tier parsing pipeline (Direct $\rightarrow$ Markdown Fence Stripping $\rightarrow$ Regex `{...}` block extraction) paired with a **deterministic fallback synthesizer**.
* **Rationale:** If Ollama is offline or times out ($> 4.0\text{s}$), the fallback synthesizer extracts an immediate combat card directly from the transcript text using sentence boundary regex in **20 ms**. **The HUD never crashes.**

---

### ADR-009: Subtitle-First Ingestion with yt-dlp (Skipping Media Downloads)
* **Date:** Phase 3
* **Context:** Downloading video files or high-bitrate audio to run speech recognition takes 15–45 seconds and wastes disk/network bandwidth. Over 90% of YouTube gaming videos already contain English subtitles.
* **Decision:** Use `yt-dlp` with `skip_download: True` to fetch `.json3` / `.vtt` timedtext tracks directly into memory via HTTP GET.
* **Rationale:** Extracts full transcript timelines in **< 1.0 second**, using zero audio disk I/O and zero GPU compute.

---

### ADR-010: Overlapping Sliding Window Chunking (35s Window, 15s Stride)
* **Date:** Phase 3
* **Context:** Subtitle cues arrive in 2–4 second fragments. Indexing individual cues splits enemy telegraphs from the corresponding counter action.
* **Decision:** Implement [`chunk_cues_sliding_window`](file:///home/ewan/Projects/wayfinder/core/ingestion/chunker.py#L55) with a 35s window and 15s stride, coupled with token history de-duplication to eliminate Google ASR rolling repetitions.
* **Rationale:** Preserves complete combat action loops across cutoffs while eliminating speech stutters.

---

### ADR-011: Strict CPU INT8 Whisper Fallback via faster-whisper
* **Date:** Phase 3
* **Context:** Videos with zero subtitles require audio transcription, but PyTorch Whisper consumes significant GPU VRAM needed by the running game.
* **Decision:** Implement [`WhisperTranscriber`](file:///home/ewan/Projects/wayfinder/core/ingestion/transcriber.py#L25) using `faster-whisper` (CTranslate2) with `device="cpu"` and `compute_type="int8"`.
* **Rationale:** Keeps **100% of GPU VRAM free** for the active game while transcribing on 4 CPU threads.

---

### ADR-012: Python Package Management with `uv` and Python 3.12
* **Date:** Phase 2
* **Context:** Fast dependency installation and isolated virtual environment management.
* **Decision:** Standardize on `uv` managing `.venv` with Python 3.12.
* **Rationale:** Resolves and installs packages in milliseconds, manages Python versions automatically, and guarantees pre-built binary wheels for CTranslate2 and Pydantic.

### ADR-013: FastAPI Micro-Daemon with Worker Threadpools & Multi-Threaded SQLite
* **Date:** Phase 4
* **Context:** The Tauri overlay requires sub-millisecond status checks, catalog lookups, and combat query responses without freezing when the local SLM is performing token inference or when accessed across multiple threads.
* **Decision:** Implement a micro FastAPI server ([`core/server.py`](file:///home/ewan/Projects/wayfinder/core/server.py)) using threadpool offloading (`def execute_query`) paired with `sqlite3.connect(..., check_same_thread=False)`. Wrap all query results in an envelope model (`found`, `card`, `telemetry`).
* **Rationale:** Keeps the asyncio event loop responsive (<1ms `/health` responses) even while local SLM token generation is in flight. Enables safe multi-threaded SQLite reads across AnyIO worker threads while WAL mode eliminates read locks.

---

## 3. Current Project State & Verification Matrix

All milestones for **Phases 1, 2, and 3** are fully implemented, tested, and passing on local hardware.

| Milestone | Deliverable Component | Invariant / Target | Measured Metric | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | SQLite + FTS5 Retrieval Engine | Search latency `< 15.0 ms` | **0.150 ms** average | **PASS** |
| **Phase 2** | Local SLM Structured Synthesizer | Valid JSON card `< 1.5s`, 0% schema errors | **1.45s** avg, **0% errors** across test suite | **PASS** |
| **Phase 3** | Subtitle-First Ingestion Pipeline | Captions parsed `< 1.0s`, Whisper fallback operational | **0.86s** parsing, CPU INT8 operational | **PASS** |
| **Phase 4** | Tauri v2 Transparent Overlay HUD | Seamless `Alt+G` toggle, idle RAM `< 35MB` | *Up Next* | **PENDING** |
| **Phase 5** | Sekiro MVP Dogfooding & Stress Test | 0 dropped game frames | *Final Step* | **PENDING** |

---

## 4. What We Plan To Do Next: Phase 4 & Phase 5 Roadmap

### Phase 4: The Interface (Tauri v2 Overlay & IPC Bridge)

Now that the backend retrieval, synthesis, and ingestion engines are rock solid, we wrap the engine in a transparent desktop HUD.

```
┌────────────────────────────────────────────────────────┐
│               ACTIVE GAME (Sekiro 60 FPS)              │
│               [Borderless Windowed Mode]               │
│                                                        │
│   ┌──────────────────────────────────────────────┐     │
│   │ Wayfinder Transparent HUD (Alt + G)          │     │
│   │ ┌──────────────────────────────────────────┐ │     │
│   │ │ [Sekiro] How to counter lightning?     🔍│ │     │
│   │ ├──────────────────────────────────────────┤ │     │
│   │ │ GENICHIRO ASHINA [Phase 3]               │ │     │
│   │ │ • TELL: Leaps into air charged with aura │ │     │
│   │ │ • ACTION: Jump, attack (R1) mid-air      │ │     │
│   │ │ • OUTCOME: Stuns boss 5s, posture damage │ │     │
│   │ └──────────────────────────────────────────┘ │     │
│   └──────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────┘
```

#### Detailed Steps for Phase 4:
1. **Lightweight Daemon Server ([`core/server.py`](file:///home/ewan/Projects/wayfinder/core/server.py)) — [COMPLETED]:**
   * Built FastAPI / Uvicorn micro-daemon with `check_same_thread=False` and threadpool routing.
   * `POST /query`: takes `{ "game_id": "sekiro", "query": "..." }`, returns `TacticalCard` envelope with sub-ms FTS and 20ms fallback.
   * `GET /games`: lists indexed games, encounters, and chunk counts.
   * `GET /health`: checks daemon status, chunk counts, and local LLM availability.
   * Verified with 100% passing tests in [`tests/test_server.py`](file:///home/ewan/Projects/wayfinder/tests/test_server.py).

2. **Scaffold Tauri v2 Frameless Window (`desktop/`) — [UP NEXT]:**
   * Configure `tauri.conf.json`:
     * `transparent: true`
     * `decorations: false`
     * `alwaysOnTop: true`
   * Frontend built with Solid.js or React + Vanilla CSS (dark mode, glassmorphism, zero dropped frames).

3. **Global Shortcuts & Input Handling:**
   * Register system-wide global shortcut: `Alt + G` to show and focus the search palette.
   * Bind `Escape` to instantly hide the overlay and return mouse/keyboard focus to the game.

4. **Startup Desktop Notification:**
   * Emit native system desktop toast on startup:
     *"Wayfinder active (Alt+G). Set your game to Borderless Windowed for overlay display."*

---

### Phase 5: Polish, Stress Testing & First User Test
1. **Resource Benchmark:**
   * Run *Sekiro* at high settings alongside Wayfinder.
   * Measure frame-times with MangoHud or RTSS to verify **zero dropped frames**.
2. **First User Field Test:**
   * Put a player in front of Genichiro or Guardian Ape with only the `Alt+G` hotkey.
   * Verify they can read and execute counters without touching a browser or second screen.
