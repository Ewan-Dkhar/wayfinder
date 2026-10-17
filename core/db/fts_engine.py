"""Full-Text Search (FTS5) BM25 retrieval engine for Wayfinder.

Provides high-speed, multi-source (YouTube, Steam, Wikis) search
with sub-millisecond query execution times and query sanitization.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Allow running directly as 'python3 core/db/fts_engine.py'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db.database import DEFAULT_DB_PATH, get_connection
from core.db.seeds.sekiro_seed import seed_sekiro


@dataclass
class SearchResult:
    """Represents a ranked combat guide search result."""

    chunk_id: int
    game_id: str
    encounter_id: str
    source_type: str  # 'youtube', 'steam', 'wiki'
    source_ref: str
    start_time: float
    end_time: float
    content_text: str
    bm25_score: float
    latency_ms: float
    clip_path: Optional[str] = None

    @property
    def has_clip(self) -> bool:
        """Indicates whether an indexed local video clip is available for this chunk."""
        return bool(self.clip_path)

    @property
    def formatted_timestamp(self) -> str:
        """Returns human-readable M:SS timestamp format for video sources."""
        if self.source_type != "youtube" or (self.start_time == 0.0 and self.end_time == 0.0):
            return "N/A (Written Guide)"
        start_min, start_sec = divmod(int(self.start_time), 60)
        end_min, end_sec = divmod(int(self.end_time), 60)
        return f"{start_min}:{start_sec:02d} - {end_min}:{end_sec:02d}"

    @property
    def source_label(self) -> str:
        """Returns a clean display label indicating the origin."""
        if self.source_type == "youtube":
            return f"YouTube [{self.formatted_timestamp}] ({self.source_ref})"
        elif self.source_type == "steam":
            return f"Steam Community Guide ({self.source_ref})"
        return f"{self.source_type.title()} ({self.source_ref})"


STOP_WORDS = {
    "how", "to", "what", "where", "when", "why", "is", "are", "the",
    "a", "an", "can", "do", "does", "i", "you", "my", "me", "for",
    "in", "on", "of", "with", "and", "or", "so", "be", "about",
}


def sanitize_query(query: str) -> str:
    """Sanitizes user input into safe, high-recall FTS5 BM25 query syntax.
    
    1. Extracts words and phrases, stripping FTS5 control operators.
    2. Filters out conversational stop words ('how', 'to', 'can I', etc.).
    3. Combines tokens using 'OR' so BM25 ranks chunks with the highest IDF
       and term overlap without failing when conversational filler is absent.
    """
    raw_tokens = re.findall(r"\b[\w\-]+\b", query)
    if not raw_tokens:
        return ""

    # Filter stop words (case-insensitive)
    filtered = [t for t in raw_tokens if t.lower() not in STOP_WORDS]
    target_tokens = filtered if filtered else raw_tokens

    # Wrap each token in double quotes to prevent syntax collisions
    escaped_tokens = [f'"{token}"' for token in target_tokens]
    return " OR ".join(escaped_tokens)


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
        source_type: Optional[str] = None,
        limit: int = 5,
    ) -> List[SearchResult]:
        """Executes a BM25 ranked search for the given query and filters.
        
        Measures precise wall-clock latency down to microsecond precision.
        """
        sanitized = sanitize_query(query)
        if not sanitized:
            return []

        sql = """
            SELECT 
                c.id,
                c.game_id,
                c.encounter_id,
                c.source_type,
                c.source_ref,
                c.start_time,
                c.end_time,
                c.content_text,
                c.clip_path,
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

        if source_type:
            sql += " AND c.source_type = :source_type"
            params["source_type"] = source_type

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
                source_type=row["source_type"],
                source_ref=row["source_ref"],
                start_time=row["start_time"],
                end_time=row["end_time"],
                content_text=row["content_text"],
                clip_path=row["clip_path"],
                bm25_score=row["bm25_score"],
                latency_ms=latency_ms,
            )
            for row in rows
        ]
        return results

    def get_indexed_games(self) -> list[dict]:
        """Returns a list of indexed games with their encounters and chunk counts."""
        cursor = self.conn.execute(
            """
            SELECT game_id, encounter_id, count(*) AS chunk_count 
            FROM guide_chunks 
            GROUP BY game_id, encounter_id 
            ORDER BY game_id, encounter_id
            """
        )
        games_map: dict[str, dict] = {}
        for row in cursor.fetchall():
            g_id = row["game_id"]
            e_id = row["encounter_id"]
            cnt = row["chunk_count"]
            if g_id not in games_map:
                games_map[g_id] = {
                    "game_id": g_id,
                    "encounters": [],
                    "chunk_count": 0,
                }
            games_map[g_id]["encounters"].append(e_id)
            games_map[g_id]["chunk_count"] += cnt

        return list(games_map.values())

    def close(self) -> None:
        """Closes the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def run_benchmark(engine: FTSEngine, query: str, game_id: str, runs: int = 100) -> dict:
    """Runs a warm-up and multi-iteration latency benchmark."""
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
    """CLI entrypoint for testing and benchmarking the multi-source FTS engine."""
    parser = argparse.ArgumentParser(description="Wayfinder Multi-Source FTS BM25 Retrieval Engine")
    parser.add_argument("query", type=str, help="Search query (e.g. 'lightning reversal')")
    parser.add_argument("--game", type=str, default="sekiro", help="Target game_id (default: sekiro)")
    parser.add_argument("--encounter", type=str, default=None, help="Optional encounter_id filter")
    parser.add_argument("--source", type=str, default=None, choices=["youtube", "steam", "wiki"], help="Filter by source type")
    parser.add_argument("--limit", type=int, default=3, help="Max results to return")
    parser.add_argument("--benchmark", action="store_true", help="Run 100-iteration latency benchmark")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database")

    args = parser.parse_args()

    # Ensure database is seeded
    seed_sekiro(args.db)

    engine = FTSEngine(db_path=args.db)

    print("\n" + "=" * 70)
    print(f"🔍 QUERY: '{args.query}' | GAME: '{args.game}'" + (f" | SOURCE: '{args.source}'" if args.source else ""))
    print("=" * 70)

    results = engine.search(
        query=args.query,
        game_id=args.game,
        encounter_id=args.encounter,
        source_type=args.source,
        limit=args.limit,
    )

    if not results:
        print("\n❌ No matching combat chunks found.")
    else:
        print(f"\n✅ Found {len(results)} matches in {results[0].latency_ms:.3f} ms:\n")
        for i, res in enumerate(results, start=1):
            print(f"[{i}] Boss: {res.encounter_id.upper()} | {res.source_label} (Score: {res.bm25_score:.3f})")
            print(f"    Content: \"{res.content_text}\"\n")

    if args.benchmark or True:
        print("-" * 70)
        print("📊 LATENCY BENCHMARK (100 Iterations):")
        stats = run_benchmark(engine, query=args.query, game_id=args.game, runs=100)
        print(f"   • Min Latency: {stats['min_ms']:.3f} ms")
        print(f"   • Avg Latency: {stats['avg_ms']:.3f} ms")
        print(f"   • p50 Latency: {stats['p50_ms']:.3f} ms")
        print(f"   • p95 Latency: {stats['p95_ms']:.3f} ms")
        print(f"   • Max Latency: {stats['max_ms']:.3f} ms")

        if stats["p95_ms"] < 15.0:
            print("\n🎯 INVARIANT PASSED: p95 retrieval latency is well under 15ms!")
        else:
            print("\n⚠️ INVARIANT FAILED: Retrieval latency exceeded 15ms target.")
        print("=" * 70 + "\n")

    engine.close()


if __name__ == "__main__":
    main()
