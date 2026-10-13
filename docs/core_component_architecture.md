# Wayfinder — Core Component Architecture

## 1. Universal Ingestion & Normalization Worker
- **Role:** Converts any YouTube URL or video file into structured, timestamped transcript chunks tagged with `game_id`.
- **Workflow:**
  1. Parse video metadata and verify caption track availability via `yt-dlp`.
  2. If captions exist: stream and normalize directly into timestamped windows.
  3. If captions are missing: stream audio directly into `faster-whisper` (int8).
  4. Commit normalized chunks to the SQLite database.

## 2. Universal Game Index & Retrieval Engine
- **Role:** Fast, multi-game search index isolating queries to the player's active game.
- **Database Schema:**
```sql
CREATE TABLE guide_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,          -- e.g., 'sekiro', 'wukong', 'elden_ring'
    encounter_id TEXT NOT NULL,     -- e.g., 'genichiro', 'tiger_vanguard'
    video_id TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    transcript_text TEXT NOT NULL
);

CREATE VIRTUAL TABLE guide_fts USING fts5(
    game_id,
    encounter_id,
    transcript_text,
    content='guide_chunks',
    content_rowid='id'
);
```

## 3. Universal Tactical Synthesizer
- **Role:** Extracts universal combat and traversal advice based on player query context.
- **Schema Definition:**
```json
{
  "game": "string",
  "encounter": "string",
  "phase_or_area": "string",
  "summary": "string (max 15 words)",
  "tactical_cues": [
    {
      "tell": "string (visual/audio warning sign)",
      "action": "string (precise button input, dodge direction, or parry timing)",
      "outcome": "string (punish window or hazard avoided)"
    }
  ],
  "key_setup": ["string (recommended item, spell, or prosthetic)"]
}
```

## 4. Overlay HUD Window
- **Role:** Renders the tactical cheat sheet over the active game display.
- **Window Rules:**
  - Borderless, frameless, transparent.
  - Activated by `Alt + G`.
  - Dismissed by `Esc` or losing focus.
  - Initial startup notification warns users to use **"Borderless Windowed"** mode in their game settings.