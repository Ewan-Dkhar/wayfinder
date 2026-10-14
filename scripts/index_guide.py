"""Universal Ingestion CLI for Wayfinder.

Ingests YouTube walkthroughs, Steam Community Guides, or local Markdown files,
chunks them into combat windows, and commits them to SQLite FTS5 for instant search.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db.database import (
    DEFAULT_DB_PATH,
    GuideChunk,
    get_connection,
    init_db,
    insert_chunks_batch,
)
from core.db.fts_engine import FTSEngine
from core.ingestion.chunker import (
    CaptionCue,
    IngestChunk,
    chunk_cues_sliding_window,
)
from core.ingestion.steam_parser import SteamGuideParser
from core.ingestion.transcriber import WhisperTranscriber
from core.ingestion.yt_parser import YouTubeCaptionParser


def index_youtube(
    url: str,
    game_id: str,
    encounter_id: str,
    window_s: float = 35.0,
    stride_s: float = 15.0,
    force_whisper: bool = False,
) -> List[GuideChunk]:
    """Ingests YouTube video: Subtitle-first with Whisper audio fallback."""
    yt_parser = YouTubeCaptionParser()
    print(f"\n[1/3] Inspecting YouTube URL via yt-dlp: {url}")
    t0 = time.perf_counter_ns()

    yt_res = yt_parser.parse(url)
    cues: List[CaptionCue] = []
    source_ref = yt_res.video_id

    if yt_res.has_subtitles and not force_whisper:
        print(f"      ✅ Found {yt_res.track_type.upper()} English subtitles in {yt_res.latency_ms:.1f}ms ({len(yt_res.cues)} raw cues)")
        cues = yt_res.cues
    else:
        reason = "Forced by user" if force_whisper else "Zero subtitle tracks found"
        print(f"      ⚠️  {reason}. Triggering Whisper fallback worker (int8 CPU)...")
        transcriber = WhisperTranscriber()
        t_w0 = time.perf_counter_ns()
        cues = transcriber.transcribe(url)
        t_w1 = time.perf_counter_ns()
        print(f"      ✅ Transcribed {len(cues)} audio cues in {(t_w1 - t_w0)/1_000_000:.1f}ms")

    # Step 2: Sliding window chunking
    print(f"[2/3] Chunking into {window_s}s windows (stride={stride_s}s)...")
    raw_chunks = chunk_cues_sliding_window(
        cues=cues,
        window_seconds=window_s,
        stride_seconds=stride_s,
    )
    print(f"      Generated {len(raw_chunks)} overlapping combat chunks.")

    return [
        GuideChunk(
            game_id=game_id,
            encounter_id=encounter_id,
            source_type="youtube",
            source_ref=source_ref,
            start_time=c.start_time,
            end_time=c.end_time,
            content_text=c.content_text,
        )
        for c in raw_chunks
    ]


def index_steam(
    url: str,
    game_id: str,
    encounter_id: str,
) -> List[GuideChunk]:
    """Ingests Steam Community Guide."""
    parser = SteamGuideParser()
    print(f"\n[1/2] Fetching Steam Guide: {url}")
    res = parser.parse_url(url)
    print(f"      ✅ Parsed {res.section_count} sections in {res.latency_ms:.1f}ms")

    return [
        GuideChunk(
            game_id=game_id,
            encounter_id=encounter_id,
            source_type="steam",
            source_ref=res.source_id,
            start_time=0.0,
            end_time=0.0,
            content_text=c.content_text,
        )
        for c in res.chunks
    ]


def index_markdown(
    file_path: Path,
    game_id: str,
    encounter_id: str,
) -> List[GuideChunk]:
    """Ingests local Markdown guide file."""
    parser = SteamGuideParser()
    print(f"\n[1/2] Reading local Markdown file: {file_path}")
    res = parser.parse_markdown_file(file_path)
    print(f"      ✅ Extracted {len(res.chunks)} sections in {res.latency_ms:.2f}ms")

    return [
        GuideChunk(
            game_id=game_id,
            encounter_id=encounter_id,
            source_type="wiki",
            source_ref=res.source_id,
            start_time=0.0,
            end_time=0.0,
            content_text=c.content_text,
        )
        for c in res.chunks
    ]


def main() -> None:
    """CLI entrypoint for guide ingestion."""
    parser = argparse.ArgumentParser(description="Wayfinder Universal Guide Ingestion CLI")
    parser.add_argument("--url", type=str, default=None, help="YouTube URL or Steam Community Guide URL")
    parser.add_argument("--file", type=str, default=None, help="Local Markdown file path")
    parser.add_argument("--game", type=str, required=True, help="Target game ID (e.g. 'sekiro', 'wukong')")
    parser.add_argument("--boss", type=str, required=True, help="Target encounter/boss ID (e.g. 'genichiro')")
    parser.add_argument("--window", type=float, default=35.0, help="Sliding window size in seconds (default: 35.0)")
    parser.add_argument("--stride", type=float, default=15.0, help="Window stride in seconds (default: 15.0)")
    parser.add_argument("--force-whisper", action="store_true", help="Force Whisper audio fallback")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    args = parser.parse_args()

    if not args.url and not args.file:
        print("❌ Error: Must specify either --url or --file.")
        sys.exit(1)

    print("=" * 70)
    print(f"📥 WAYFINDER INGESTION ENGINE | GAME: {args.game.upper()} | BOSS: {args.boss.upper()}")
    print("=" * 70)

    t_start = time.perf_counter_ns()

    chunks_to_insert: List[GuideChunk] = []

    if args.file:
        chunks_to_insert = index_markdown(Path(args.file), args.game, args.boss)
    elif "steamcommunity.com" in args.url:
        chunks_to_insert = index_steam(args.url, args.game, args.boss)
    else:
        chunks_to_insert = index_youtube(
            url=args.url,
            game_id=args.game,
            encounter_id=args.boss,
            window_s=args.window,
            stride_s=args.stride,
            force_whisper=args.force_whisper,
        )

    if not chunks_to_insert:
        print("\n❌ Ingestion failed: No content chunks extracted.")
        sys.exit(1)

    # Step 3: Insert into SQLite
    print(f"\n[3/3] Committing {len(chunks_to_insert)} chunks to SQLite database...")
    init_db(args.db)
    conn = get_connection(args.db)
    with conn:
        count = insert_chunks_batch(conn, chunks_to_insert)

    t_end = time.perf_counter_ns()
    total_ms = (t_end - t_start) / 1_000_000.0

    print("-" * 70)
    print(f"🎉 SUCCESS: Indexed {count} chunks in {total_ms:.1f}ms total pipeline time!")
    print(f"   Database: {args.db}")
    print("   SQLite triggers synchronized inverted FTS5 index automatically.")
    print("=" * 70 + "\n")

    # Immediate verification search
    print("🔍 VERIFICATION QUERY (Testing immediate retrieval)...")
    engine = FTSEngine(db_path=args.db)
    sample_res = engine.search(query=args.boss, game_id=args.game, limit=2)
    for i, r in enumerate(sample_res, 1):
        print(f"   [{i}] {r.encounter_id.upper()} | {r.source_label} ({r.latency_ms:.3f}ms):")
        print(f"       \"{r.content_text[:90]}...\"\n")
    engine.close()


if __name__ == "__main__":
    main()
