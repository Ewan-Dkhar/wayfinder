# 🧭 Wayfinder

> **Sub-millisecond, local-first in-game companion HUD for action RPGs & Soulslike titles.**  
> Synthesizes authoritative boss & combat cheat sheets on demand using SQLite FTS5 BM25 retrieval and local SLM distillation.

---

## ⚡ The Problem & The Vision

When facing challenging bosses in games like *Sekiro: Shadows Die Twice*, *Elden Ring*, or *Lies of P*, players often hit walls. Existing solutions force painful tradeoffs:
1. **Alt-Tabbing to YouTube / Wikis:** Breaks combat flow, causes window focus lag, and forces reading through 20-minute video fluff or walls of text while tabbed out.
2. **Second-Monitor Wikis:** Distracts eye tracking from enemy telegraphs and attack animations.
3. **Heavy Overlays (Electron / Overwolf):** Steal precious CPU/GPU cycles, introduce frame pacing stutter (frame time spikes >16.6ms), and inject bloated chromium runtimes.

**Wayfinder** is engineered from **First Principles** to solve this:
* **Instant Summon (`Alt + G`):** A frameless, transparent HUD overlay summoned directly over your game in borderless windowed mode.
* **Sub-Millisecond Retrieval:** SQLite FTS5 full-text search with BM25 ranking queries local game knowledge in **<1ms**.
* **3-Bullet Tactical Distillation:** Powered by local SLMs (e.g. `Qwen2.5-1.5B` via Ollama) to distill strategy into telegraph counters, weaknesses, and phase transitions in under 1 second without sending your gameplay data to the cloud.
* **Zero Frame Drop:** Lightweight Tauri v2 + Vanilla TypeScript webview with minimal DOM mutations (<0.1ms render budget), avoiding frame drops in 60/144 FPS titles.
* **Dynamic SLM Hot-Swapping:** Auto-detects all models downloaded in Ollama with a live HUD header dropdown; switch between lightweight 1.5B and heavier 7B models on the fly with zero terminal commands.
* **Multi-Game Ingestion:** Drag-and-drop community guides, YouTube video transcripts, or Steam Community guides to ingest new games on the fly.

---

## 🏗️ Architecture Overview

Wayfinder follows a decoupled, local-first client-daemon architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                      Wayfinder HUD                          │
│        (Tauri v2 + Vanilla TypeScript + Glassmorphism)      │
│  - Summon: Alt + G Hotkey     - Focus Hand-off: Escape      │
│  - Multi-Game Switcher        - Dynamic SLM Model Picker    │
│  - Drag-and-Drop Ingestion    - 0.08ms DOM Mutation Budget  │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON (127.0.0.1:8765)
┌──────────────────────────────▼──────────────────────────────┐
│                  Wayfinder Micro-Daemon                     │
│               (FastAPI + SQLite WAL Engine)                 │
│                                                             │
│  ┌───────────────────────────┐ ┌──────────────────────────┐ │
│  │   SQLite FTS5 + BM25      │ │     Distillation Engine  │ │
│  │  - Sub-ms exact retrieval │ │  - Local Ollama SLM API  │ │
│  │  - Zero B-tree lock (WAL) │ │  - Dynamic Hot-Swapping  │ │
│  └───────────────────────────┘ └──────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────┘
                               │ Local IPC (127.0.0.1:11434)
┌──────────────────────────────▼──────────────────────────────┐
│                    Ollama Runtime                           │
│                 (qwen2.5:1.5b-instruct)                     │
│  - Local GPU/NPU inference with 0 cloud latency             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

Wayfinder is designed to run 100% locally on your machine.

1. **Ollama** (Local LLM/SLM Runner):
   * Install from [ollama.com](https://ollama.com).
   * Pull the lightweight 1.5B distillation model:
     ```bash
     ollama pull qwen2.5:1.5b
     ```
   * Ensure Ollama is running in the background (`ollama serve`).

---

## 🚀 Quickstart (Development Mode)

### 1. Clone & Set Up the Python Micro-Daemon
```bash
git clone https://github.com/Ewan-Dkhar/wayfinder.git
cd wayfinder

# Install dependencies using uv (or standard pip)
uv sync

# Run database tests to verify SQLite FTS5 & endpoints
uv run pytest

# Launch the micro-daemon
uv run uvicorn core.server:app --port 8765
```

### 2. Launch the Tauri HUD Overlay
In a separate terminal:
```bash
cd desktop
npm install

# On Linux (NVIDIA / WebKitGTK fix included):
npm run tauri dev
```

> [!TIP]
> **Zero-Friction Dev Setup:** You do **not** need to compile the 140MB PyInstaller sidecar binary for local development! Wayfinder's Cargo build script automatically provisions a lightweight development stub on your first `npm run tauri dev`. The desktop HUD will connect directly to your live FastAPI daemon running on `127.0.0.1:8765`.

---

## 🎮 How to Use in Game

1. **Launch Your Game:** Set display mode to **Borderless Windowed** (recommended for seamless overlay rendering).
2. **Summon HUD:** Press **`Alt + G`** at any moment in combat.
3. **Search Instantly:** Start typing the encounter name (e.g. `Genichiro`, `Guardian Ape`).
4. **Read Tactical Cheat Sheet:** Review the 3 distilled bullets:
   * **Telegraph & Counter:** Critical perilous attacks and how to deflect/dodge them.
   * **Key Vulnerability:** Effective prosthetic tools, items, or element weaknesses.
   * **Phase Shift:** Tactical shifts between battle phases.
5. **Dismiss:** Press **`Escape`** or click outside to instantly return input focus to your game.

---

## 📥 Ingesting Custom Guides

Wayfinder includes a built-in guide ingestion pipeline in the HUD:
1. Click the **`+ Add Guide`** button in the top header.
2. Select or enter the target game ID (e.g. `elden_ring`, `sekiro`, `black_myth_wukong`).
3. Choose your source:
   * **URL Tab:** Paste a YouTube combat guide URL or Steam Community Guide URL.
   * **File Tab:** Drag and drop any `.md` markdown guide or wiki export.
4. Click **`Ingest Guide`**. Wayfinder will parse, chunk, canonicalize encounter tags, index into SQLite FTS5, and switch your active game automatically!

---

## 🤖 Dynamic Local SLM Switching

Wayfinder does **not** hardcode models. The desktop HUD automatically queries Ollama via `GET /models` and populates the model pill dropdown in the top header.

* **Switch Models in 1 Click:** Select any model installed in your local Ollama instance (e.g. `llama3.2:3b`, `qwen2.5:1.5b`, `deepseek-r1:1.5b`).
* **Instant Hot-Swapping:** Wayfinder hot-swaps the model in memory immediately via `POST /settings/model` without needing a daemon or app restart.
* **Persistent Preference:** Your model choice is saved to standard OS app storage (`~/.config/wayfinder/config.json` on Linux, `%APPDATA%\wayfinder\config.json` on Windows) and remembered across boots.

### Recommended Hardware Tiers:
| Hardware Profile | Recommended Model | Latency | VRAM Footprint |
| :--- | :--- | :--- | :--- |
| **Handheld / Low VRAM (<4GB)** (e.g. Steam Deck, Laptop iGPU) | `qwen2.5:1.5b` or `qwen2.5:0.5b` | ~700ms | ~1.2 GB |
| **Mid-Range Gaming PC (6GB–8GB VRAM)** (e.g. RTX 3060, 4060) | `llama3.2:3b` or `qwen2.5:3b` | ~900ms | ~2.5 GB |
| **High-End Enthusiast (12GB+ VRAM)** (e.g. RTX 4080, 4090) | `qwen2.5:7b` or `deepseek-r1:8b` | ~1100ms | ~5.2 GB |

---

## 📦 Zero-Terminal Packaging Guide

To bundle Wayfinder into a single desktop application that users can double-click and run without opening a terminal, Tauri uses the **Sidecar Pattern**.

### Concept: The Tauri Sidecar Pipeline
In production, the Python daemon is packaged into a standalone binary using **PyInstaller** and embedded directly into the Tauri bundle. The Rust core automatically starts the daemon on boot and terminates it when the HUD exits.

```
Installer (.deb / .AppImage / .exe / .msi)
  ├── wayfinder (Tauri native launcher)
  ├── wayfinder-daemon (Embedded PyInstaller standalone daemon)
  └── resources/
        └── wayfinder.db (Pre-indexed guide catalog)
```

### Build Steps:

#### Prerequisites
* **Rust:** Stable toolchain (`rustup default stable`)
* **Node.js:** v18+ & npm
* **Python:** 3.12+ managed via `uv`
* **OS Build Libraries (Linux only):**
  * *Arch Linux:* `sudo pacman -S webkit2gtk-4.1 libappindicator-gtk3 base-devel`
  * *Ubuntu/Debian:* `sudo apt install libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf`

---

#### Step 1: Compile & Stage the Python Sidecar Daemon
Wayfinder includes an automated build script ([`scripts/build_sidecar.py`](scripts/build_sidecar.py)) that detects your host's Rust target triple, runs PyInstaller with all required hidden imports via [`wayfinder-daemon.spec`](wayfinder-daemon.spec), stages the binary into `desktop/src-tauri/binaries/`, and performs an automated live health probe:

```bash
# In the repository root
uv run python scripts/build_sidecar.py
```

Output:
```
📦 [1/4] Running PyInstaller to freeze Python micro-daemon...
✅ [2/4] PyInstaller binary compiled successfully: dist/wayfinder-daemon (140.3 MB)
🚚 [3/4] Staging sidecar binary for Tauri v2...
✅ Staged sidecar binary: desktop/src-tauri/binaries/wayfinder-daemon-<target-triple>
🔍 [4/4] Performing live smoke test on compiled sidecar binary...
🎉 [SUCCESS] Compiled binary passed all health probes!
```

> [!NOTE]
> Compiled sidecar binaries in `desktop/src-tauri/binaries/` are excluded from Git via `.gitignore` to keep repositories under GitHub's 100MB file limit.

---

#### Step 2: Build the Final Desktop Application Bundle
Once the sidecar is staged, compile the native installer with Tauri:

```bash
cd desktop
npm install
npm run tauri build
```

*(Or run `npm run build:all` to compile both the sidecar and Tauri bundle in one command!)*

This generates production-ready installers with the daemon embedded inside:
* **Linux:** Standalone `.AppImage` and `.deb` in `desktop/src-tauri/target/release/bundle/`
* **Windows:** `.msi` and `.exe` installers in `desktop/src-tauri/target/release/bundle/msi/`

The end user simply double-clicks the installer—no Python, no Node.js, and no terminal required!

---

## 🛡️ Performance & Frame Pacing

| Metric | Target | Actual |
| :--- | :--- | :--- |
| **Summon Latency (`Alt + G`)** | < 16ms (1 frame @ 60 FPS) | **~3.2ms** |
| **FTS5 BM25 Search** | < 5ms | **0.42ms** |
| **Local SLM Distillation** | < 1500ms | **720ms - 1100ms** (RTX 4060 Mobile) |
| **DOM Mutation Pacing** | < 1ms | **0.08ms** (Pure Vanilla TS) |
| **Idle Memory Footprint** | < 100MB | **~42MB** |

---

## 📚 Technical Documentation

For in-depth architectural diagrams, design decisions, and benchmarks:
* [Architectural Decision Log (ADR-001 to ADR-017)](docs/architectural_decision_log.md)
* [Engineering Concepts Handbook](docs/engineering_concepts_handbook.md)
* [AI Agent Context Rules](docs/ai_agent_context_rules.md)

---

## 📜 License
MIT License. Crafted for gamers and performance purists.
