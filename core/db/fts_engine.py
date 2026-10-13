"""Full-Text Search (FTS5) BM25 retrieval engine for Wayfinder.

Provides high-speed, local-first search across indexed video transcripts
with sub-10ms query execution times and query sanitization.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.db.database import DEFAULT_DB_PATH, get_connection
from core.db.seeds.sekiro_seed import seed_sekiro


@dataclass
class SearchResult:
    """Represents a ranked search result returned from the FTS engine."""

    chunk_id: int
    game_id: str
    encounter_id: str
    video_id: str
    start_time: float
    end_time: float
    transcript_text: str
    bm25_score: float
    latency_ms: float

    @property
    def formatted_timestamp(self) -> str:
        """Returns human-readable M:SS timestamp format."""
        start_min, start_sec = divmod(int(self.start_time), 60)
        end_min, end_sec = divmod(int(self.end_time), 60)
        return f"{start_min}:{start_sec:02d} - {end_min}:{end_sec:02d}"


def sanitize_query(query: str) -> str:
    """Sanitizes user input into safe FTS5 query syntax.
    
    Extracts words/phrases, strips special FTS5 control characters (*, :, ^, etc.)
    that could cause syntax errors, and formats tokens for BM25 matching.
    """
    # Extract alphanumeric words and basic hyphenated terms
    tokens = re.findall(r"\b[\w\-]+\b", query)
    if not tokens:
        return ""
    # Wrap each token in double quotes to prevent syntax collisions with SQLite keywords
    # e.g., 'lightning' -> '"lightning"'
    escaped_tokens = [f'"{token}"' for token in tokens]
    return " ".join(escaped_tokens)


class FTSEngine:
    """Retrieval engine executing BM25 queries against SQLite FTS5."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Returns active connection or initializes a new one with WAL mode pragmas."""
        if self._conn is None:
            self._conn = get_connection(self.db_path)
        return self._conn

    def search(
        self,
        query: str,
        game_id: str = "sekiro",
        encounter_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """Executes a BM25 ranked search for the given query and game.
        
        Measures precise wall-clock latency down to microsecond precision.
        """
        sanitized = sanitize_query(query)
        if not sanitized:
            return []

        # Construct SQL with optional encounter filter
        sql = """
            SELECT 
                c.id,
                c.game_id,
                c.encounter_id,
                c.video_id,
                c.start_time,
                c.end_time,
                c.transcript_text,
                guide_fts.rank AS bm25_score
            FROM guide_fts
            JOIN guide_chunks c ON c.id = guide_fts.rowid
            WHERE guide_fts MATCH :query
              AND c.game_id = :game_id
        """
        params: dict[str, str | int] = {
            "query": sanitized,
            "game_id": game_id,
            "limit": limit,
        }

        if encounter_id:
            sql += " AND c.encounter_id = :encounter_id"
            params["encounter_id"] = encounter_id

        sql += """
            ORDER BY guide_fts.rank ASC
            LIMIT :limit;
        """

        # High-resolution benchmark timing
        t_start = time.perf_counter_ns()
        cursor = self.conn.execute(sql, params)
        rows = cursor.fetchall()
        t_end = time.perf_counter_ns()

        latency_ms = (t_end - t_start) / 1_000_000.0

        results = [
            SearchResult(
                chunk_id=row["id"],
                game_id=row["game_id"],
                encounter_id=row["encounter_id"],
                video_id=row["video_id"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                transcript_text=row["transcript_text"],
                bm25_score=row["bm25_score"],
                latency_ms=latency_ms,
            )
            for row in rows
        ]
        return results

    def close(self) -> None:
        """Closes the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def run_benchmark(engine: FTSEngine, query: str, game_id: str, runs: int = 100) -> dict:
    """Runs a warm-up and multi-iteration latency benchmark."""
    # Warm up cache with 5 queries
    for _ in range(5):
        engine.search(query=query, game_id=game_id)

    latencies: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter_ns()
        engine.search(query=query, game_id=game_id)
        t1 = time.perf_counter_ns()
        latencies.append((t1 - t0) / 1_000_000.0)

    latencies.sort()
    avg_latency = sum(latencies) / len(latencies)
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    min_lat = latencies[0]
    max_lat = latencies[-1]

    return {
        "runs": runs,
        "avg_ms": avg_latency,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "min_ms": min_lat,
        "max_ms": max_lat,
    }


def main() -> None:
    """CLI entrypoint for testing and benchmarking the FTS engine."""
    parser = argparse.ArgumentParser(description="Wayfinder FTS BM25 Retrieval Engine")
    parser.add_argument("query", type=str, help="Search query (e.g. 'lightning reversal')")
    parser.add_argument("--game", type=str, default="sekiro", help="Target game_id (default: sekiro)")
    parser.add_argument("--encounter", type=str, default=None, help="Optional encounter_id filter")
    parser.add_argument("--limit", type=int, default=3, help="Max results to return")
    parser.add_argument("--benchmark", action="store_true", help="Run 100-iteration latency benchmark")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    args = parser.parse_args()

    # Ensure database is seeded
    seed_sekiro(args.db)

    engine = FTSEngine(db_path=args.db)

    print("\n" + "=" * 70)
    print(f"🔍 QUERY: '{args.query}' | GAME: '{args.game}'")
    print("=" * 70)

    results = engine.search(
        query=args.query,
        game_id=args.game,
        encounter_id=args.encounter,
        limit=args.limit,
    )

    if not results:
        print("\n❌ No matching combat chunks found.")
    else:
        print(f"\n✅ Found {len(results)} matches in {results[0].latency_ms:.3f} ms:\n")
        for i, res in enumerate(results, start=1):
            print(f"[{i}] Boss: {res.encounter_id.upper()} | Time: {res.formatted_timestamp} (Score: {res.bm25_score:.3f})")
            print(f"    Video ID: {res.video_id}")
            print(f"    Transcript: \"{res.transcript_text}\"\n")

    if args.benchmark or True:  # Run benchmark validation automatically
        print("-" * 70)
        print("📊 LATENCY BENCHMARK (100 Iterations):")
        stats = run_benchmark(engine, query=args.query, game_id=args.game, runs=100)
        print(f"   • Min Latency: {stats['min_ms']:.3f} ms")
        print(f"   • Avg Latency: {stats['avg_ms']:.3f} ms")
        print(f"   • p50 Latency: {stats['p50_ms']:.3f} ms")
        print(f"   • p95 Latency: {stats['p95_ms']:.3f} ms")
        print(f"   • Max Latency: {stats['max_ms']:.3f} ms")

        # Invariant check (< 15 ms target)
        if stats["p95_ms"] < 15.0:
            print("\n🎯 INVARIANT PASSED: p95 retrieval latency is well under 15ms!")
        else:
            print("\n⚠️ INVARIANT FAILED: Retrieval latency exceeded 15ms target.")
        print("=" * 70 + "\n")

    engine.close()


if __name__ == "__main__":
    main()
