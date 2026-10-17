"""Tests for database schema, migrations, clip metadata, and FTS5 search."""

import sqlite3
import pytest
from pathlib import Path

from core.db.database import (
    GuideChunk,
    get_connection,
    init_db,
    insert_chunk,
    insert_chunks_batch,
    get_chunk_by_id,
    update_chunk_clip,
)
from core.db.fts_engine import FTSEngine


def test_init_db_creates_clip_path_column_and_index(tmp_path: Path):
    """Verifies that a fresh database initializes with the clip_path column and index."""
    db_file = tmp_path / "fresh.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        cursor = conn.execute("PRAGMA table_info(guide_chunks);")
        columns = {row["name"]: row["type"] for row in cursor.fetchall()}
        assert "clip_path" in columns

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_chunks_clip';"
        )
        assert cursor.fetchone() is not None


def test_migration_adds_clip_path_to_legacy_db(tmp_path: Path):
    """Verifies that init_db safely migrates a legacy database missing clip_path."""
    db_file = tmp_path / "legacy.db"

    # Simulate an older schema without clip_path
    legacy_sql = """
    CREATE TABLE guide_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'youtube',
        source_ref TEXT NOT NULL,
        start_time REAL NOT NULL DEFAULT 0.0,
        end_time REAL NOT NULL DEFAULT 0.0,
        content_text TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE guide_fts USING fts5(
        content_text,
        content='guide_chunks',
        content_rowid='id'
    );
    """
    with sqlite3.connect(str(db_file)) as conn:
        conn.executescript(legacy_sql)
        conn.execute(
            """
            INSERT INTO guide_chunks (
                game_id, encounter_id, source_type, source_ref, 
                start_time, end_time, content_text
            ) VALUES ('sekiro', 'genichiro', 'youtube', 'yt123', 10.0, 25.0, 'Legacy guide text')
            """
        )
        conn.commit()

    # Run init_db which should perform non-destructive migration
    init_db(db_file)

    with get_connection(db_file) as conn:
        cursor = conn.execute("PRAGMA table_info(guide_chunks);")
        columns = {row["name"]: row["type"] for row in cursor.fetchall()}
        assert "clip_path" in columns

        # Ensure existing row is preserved with NULL clip_path
        cursor = conn.execute("SELECT id, content_text, clip_path FROM guide_chunks WHERE id = 1;")
        row = cursor.fetchone()
        assert row["content_text"] == "Legacy guide text"
        assert row["clip_path"] is None


def test_insert_and_get_chunk_with_clip(tmp_path: Path):
    """Verifies inserting a chunk with a clip_path and fetching it."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    chunk = GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        source_type="youtube",
        source_ref="yt_genichiro_1",
        start_time=45.0,
        end_time=55.0,
        content_text="Watch out for Genichiro jumping slam then thrust attack.",
        clip_path="clips/sekiro/genichiro_jump_thrust.webm",
    )

    with get_connection(db_file) as conn:
        row_id = insert_chunk(conn, chunk)
        assert row_id == 1

        fetched = get_chunk_by_id(conn, row_id)
        assert fetched is not None
        assert fetched.id == 1
        assert fetched.clip_path == "clips/sekiro/genichiro_jump_thrust.webm"
        assert fetched.start_time == 45.0
        assert fetched.end_time == 55.0


def test_update_chunk_clip_and_fts_sync(tmp_path: Path):
    """Verifies updating a chunk's clip_path preserves FTS5 search index synchronization."""
    db_file = tmp_path / "test.db"
    init_db(db_file)

    chunk = GuideChunk(
        game_id="elden_ring",
        encounter_id="malenia",
        source_type="youtube",
        source_ref="yt_malenia",
        start_time=120.0,
        end_time=135.0,
        content_text="Waterfowl dance tell: Malenia leaps into the air and pauses.",
        clip_path=None,
    )

    with get_connection(db_file) as conn:
        row_id = insert_chunk(conn, chunk)
        assert row_id is not None

        # Verify initial state has no clip
        fetched = get_chunk_by_id(conn, row_id)
        assert fetched.clip_path is None

        # Update clip
        updated = update_chunk_clip(conn, row_id, "clips/elden_ring/waterfowl.webm")
        assert updated is True

        fetched_after = get_chunk_by_id(conn, row_id)
        assert fetched_after.clip_path == "clips/elden_ring/waterfowl.webm"

    # Verify FTS engine retrieves the chunk with clip_path populated
    engine = FTSEngine(db_path=db_file)
    results = engine.search(query="waterfowl dance", game_id="elden_ring")
    assert len(results) == 1
    assert results[0].chunk_id == row_id
    assert results[0].clip_path == "clips/elden_ring/waterfowl.webm"
    assert results[0].has_clip is True
