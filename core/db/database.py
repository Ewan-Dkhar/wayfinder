"""SQLite database manager and FTS5 schema initialization for Wayfinder.

Implements a source-agnostic (YouTube, Steam, Wikis) external-content FTS5 pattern
with automated triggers and WAL mode pragmas for single-digit millisecond query latency.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Locate OS-standard persistent application data directory
if sys.platform == "win32":
    APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "wayfinder"
elif sys.platform == "darwin":
    APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "wayfinder"
else:
    # Linux / FreeDesktop XDG standard: ~/.local/share/wayfinder
    APP_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "wayfinder"


def is_frozen_binary() -> bool:
    """Returns True if running inside a PyInstaller or standalone frozen bundle."""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def get_seed_db_path() -> Optional[Path]:
    """Locates the bundled initial seed database.
    
    Checks PyInstaller extraction directory (sys._MEIPASS), followed by
    development workspace root.
    """
    if hasattr(sys, "_MEIPASS"):
        meipass_db = Path(sys._MEIPASS) / "wayfinder.db"
        if meipass_db.exists():
            return meipass_db

    dev_db = Path(__file__).resolve().parent.parent.parent / "wayfinder.db"
    if dev_db.exists():
        return dev_db

    return None


def get_default_db_path() -> Path:
    """Resolves the default SQLite database path with automatic self-seeding.
    
    1. Respects WAYFINDER_DB_PATH environment variable if explicitly set (tests / dev).
    2. In frozen binaries (PyInstaller / Tauri Sidecar):
       Targets user application data directory (e.g. ~/.local/share/wayfinder/wayfinder.db)
       and automatically seeds from bundled assets if not already present.
    3. In development source tree:
       Prefers repository workspace database if present, falling back to user app data.
    """
    env_override = os.getenv("WAYFINDER_DB_PATH")
    if env_override:
        return Path(env_override).resolve()

    target_user_db = APP_DATA_DIR / "wayfinder.db"

    # In compiled standalone binaries: always use user data directory
    if is_frozen_binary():
        if target_user_db.exists():
            return target_user_db

        # First run in production: seed from bundled asset
        try:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            seed = get_seed_db_path()
            if seed and seed.exists() and seed.resolve() != target_user_db.resolve():
                shutil.copy2(seed, target_user_db)
                return target_user_db
        except Exception:
            pass

        return target_user_db

    # In development source tree mode:
    dev_db = Path(__file__).resolve().parent.parent.parent / "wayfinder.db"
    if dev_db.exists():
        return dev_db

    return target_user_db


# Default path to SQLite database file
DEFAULT_DB_PATH = get_default_db_path()


@dataclass(frozen=True)
class GuideChunk:
    """Represents a combat guidance chunk from any source (YouTube, Steam, Wiki)."""

    game_id: str
    encounter_id: str
    source_type: str  # 'youtube', 'steam', 'wiki'
    source_ref: str   # Video ID, Steam Guide URL/slug, or Wiki page
    content_text: str # Transcript or written guide excerpt
    start_time: float = 0.0  # Video start timestamp in seconds (0.0 for text guides)
    end_time: float = 0.0    # Video end timestamp in seconds (0.0 for text guides)
    id: Optional[int] = None


SCHEMA_SQL = """
-- 1. Main relational store for multi-source combat guide chunks
CREATE TABLE IF NOT EXISTS guide_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'youtube', -- 'youtube', 'steam', 'wiki'
    source_ref TEXT NOT NULL,
    start_time REAL NOT NULL DEFAULT 0.0,
    end_time REAL NOT NULL DEFAULT 0.0,
    content_text TEXT NOT NULL
);

-- Fast composite indices for filtering by game, encounter, and source type
CREATE INDEX IF NOT EXISTS idx_chunks_game_encounter 
ON guide_chunks(game_id, encounter_id);

CREATE INDEX IF NOT EXISTS idx_chunks_source 
ON guide_chunks(source_type);

-- 2. FTS5 Virtual Table using External Content pattern
-- content='guide_chunks' points to the relational table, saving disk space and avoiding duplication.
-- tokenize='unicode61 remove_diacritics 2' handles accents and normalizes case/punctuation.
CREATE VIRTUAL TABLE IF NOT EXISTS guide_fts USING fts5(
    content_text,
    content='guide_chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- 3. Synchronization Triggers to keep guide_fts automatically up-to-date with guide_chunks
CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_ai 
AFTER INSERT ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(rowid, content_text) 
    VALUES (new.id, new.content_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_ad 
AFTER DELETE ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(guide_fts, rowid, content_text) 
    VALUES ('delete', old.id, old.content_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_au 
AFTER UPDATE ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(guide_fts, rowid, content_text) 
    VALUES ('delete', old.id, old.content_text);
    INSERT INTO guide_fts(rowid, content_text) 
    VALUES (new.id, new.content_text);
END;
"""


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates a configured SQLite connection optimized for sub-10ms reads.

    Key Pragmas:
    - journal_mode = WAL: Readers never block writers; concurrent non-blocking reads.
    - synchronous = NORMAL: Eliminates redundant disk syncs during transactions.
    - cache_size = -64000: Allocates ~64MB in-memory cache for page lookups.
    - temp_store = MEMORY: Stores temporary tables and indices directly in RAM.
    """
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Performance pragmas
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")
    conn.execute("PRAGMA temp_store = MEMORY;")

    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Initializes the database schema and triggers."""
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)


def insert_chunk(conn: sqlite3.Connection, chunk: GuideChunk) -> int:
    """Inserts a single guide chunk into guide_chunks.
    
    The FTS5 virtual table is automatically updated via database trigger.
    Returns the newly inserted row ID.
    """
    cursor = conn.execute(
        """
        INSERT INTO guide_chunks (
            game_id, encounter_id, source_type, source_ref, 
            start_time, end_time, content_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chunk.game_id,
            chunk.encounter_id,
            chunk.source_type,
            chunk.source_ref,
            chunk.start_time,
            chunk.end_time,
            chunk.content_text,
        ),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def insert_chunks_batch(conn: sqlite3.Connection, chunks: Iterable[GuideChunk]) -> int:
    """Inserts multiple chunks in a single transaction for maximum speed.
    
    Returns the number of rows inserted.
    """
    rows = [
        (
            c.game_id,
            c.encounter_id,
            c.source_type,
            c.source_ref,
            c.start_time,
            c.end_time,
            c.content_text,
        )
        for c in chunks
    ]
    cursor = conn.executemany(
        """
        INSERT INTO guide_chunks (
            game_id, encounter_id, source_type, source_ref, 
            start_time, end_time, content_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return cursor.rowcount
