"""SQLite database manager and FTS5 schema initialization for Wayfinder.

Implements the external-content FTS5 pattern with automated triggers
and WAL mode pragmas for single-digit millisecond query latency.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Default path to SQLite database file
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "wayfinder.db"


@dataclass(frozen=True)
class GuideChunk:
    """Represents a timestamped gameplay transcript chunk."""

    game_id: str
    encounter_id: str
    video_id: str
    start_time: float
    end_time: float
    transcript_text: str
    id: Optional[int] = None


SCHEMA_SQL = """
-- 1. Main relational store for transcript chunks
CREATE TABLE IF NOT EXISTS guide_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    transcript_text TEXT NOT NULL
);

-- Fast composite index for isolating queries by game and boss encounter
CREATE INDEX IF NOT EXISTS idx_chunks_game_encounter 
ON guide_chunks(game_id, encounter_id);

-- 2. FTS5 Virtual Table using External Content pattern
-- content='guide_chunks' points to the relational table, saving disk space and avoiding duplication.
-- tokenize='unicode61 remove_diacritics 2' handles accents and normalizes case/punctuation.
CREATE VIRTUAL TABLE IF NOT EXISTS guide_fts USING fts5(
    transcript_text,
    content='guide_chunks',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- 3. Synchronization Triggers to keep guide_fts automatically up-to-date with guide_chunks
CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_ai 
AFTER INSERT ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(rowid, transcript_text) 
    VALUES (new.id, new.transcript_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_ad 
AFTER DELETE ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(guide_fts, rowid, transcript_text) 
    VALUES ('delete', old.id, old.transcript_text);
END;

CREATE TRIGGER IF NOT EXISTS trg_guide_chunks_au 
AFTER UPDATE ON guide_chunks 
BEGIN
    INSERT INTO guide_fts(guide_fts, rowid, transcript_text) 
    VALUES ('delete', old.id, old.transcript_text);
    INSERT INTO guide_fts(rowid, transcript_text) 
    VALUES (new.id, new.transcript_text);
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
    # Ensure parent directory exists if using a custom file path
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str)
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
        INSERT INTO guide_chunks (game_id, encounter_id, video_id, start_time, end_time, transcript_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            chunk.game_id,
            chunk.encounter_id,
            chunk.video_id,
            chunk.start_time,
            chunk.end_time,
            chunk.transcript_text,
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
            c.video_id,
            c.start_time,
            c.end_time,
            c.transcript_text,
        )
        for c in chunks
    ]
    cursor = conn.executemany(
        """
        INSERT INTO guide_chunks (game_id, encounter_id, video_id, start_time, end_time, transcript_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return cursor.rowcount
