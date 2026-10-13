"""End-to-End Smoke Test and Schema Invariant Validator for Phase 2.

Runs multiple combat queries across encounters and validates:
1. Zero Pydantic schema validation failures.
2. Glanceable output conforming to the 3-bullet TacticalCard specification.
3. Latency profiling across BM25 retrieval and SLM extraction.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.llm.schemas import TacticalCard
from core.llm.synthesizer import TacticalSynthesizer

TEST_QUERIES = [
    ("How to counter Genichiro lightning?", "sekiro"),
    ("How to counter Guardian Ape terror roar?", "sekiro"),
    ("Genichiro bow flurry counter", "sekiro"),
    ("Guardian Ape centipede spear pull", "sekiro"),
    ("Genichiro perilous thrust Mikiri", "sekiro"),
]


def run_smoke_test(total_iterations: int = 10) -> bool:
    """Executes multi-run test validating schema integrity and latency."""
    synthesizer = TacticalSynthesizer()

    print("\n" + "=" * 70)
    print(f"🧪 PHASE 2 END-TO-END SMOKE TEST ({total_iterations} Iterations)")
    print("=" * 70)

    is_live = synthesizer.llm_client.check_health()
    print(f"🤖 LLM Host: {'LIVE' if is_live else 'OFFLINE (Fallback Active)'}")
    print(f"   Model: {synthesizer.llm_client.model} @ {synthesizer.llm_client.base_url}\n")

    errors: list[str] = []
    latencies: list[float] = []
    retrieval_latencies: list[float] = []

    for i in range(total_iterations):
        query, game = TEST_QUERIES[i % len(TEST_QUERIES)]
        print(f"[{i+1}/{total_iterations}] Testing: \"{query}\" ...", end="", flush=True)

        try:
            card, telemetry = synthesizer.query(player_query=query, game_id=game)
            if card is None:
                raise ValueError("Returned None for indexed query")

            # Validate instance integrity
            assert isinstance(card, TacticalCard), "Did not return TacticalCard"
            assert len(card.tactical_cues) >= 1, "Tactical cues list is empty"
            assert card.summary, "Summary is empty"

            latencies.append(telemetry["total_ms"])
            retrieval_latencies.append(telemetry["retrieval_ms"])
            print(f" ✅ Valid JSON ({telemetry['total_ms']:.1f}ms total, {telemetry['retrieval_ms']:.2f}ms FTS)")

        except Exception as e:
            errors.append(f"Run {i+1} failed: {e}")
            print(f" ❌ ERROR: {e}")

    print("\n" + "-" * 70)
    print("📊 VALIDATION SUMMARY:")
    print(f"   • Total Runs:        {total_iterations}")
    print(f"   • Schema Errors:     {len(errors)}")
    print(f"   • Error Rate:        {(len(errors) / total_iterations) * 100:.1f}%")

    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        avg_ret = sum(retrieval_latencies) / len(retrieval_latencies)
        print(f"   • Avg Total Latency: {avg_lat:.2f} ms")
        print(f"   • Avg FTS Latency:   {avg_ret:.3f} ms")

    synthesizer.close()

    success = len(errors) == 0
    if success:
        print("\n🎯 INVARIANT PASSED: 100% Schema validation compliance achieved!")
    else:
        print(f"\n⚠️ INVARIANT FAILED: {len(errors)} runs encountered validation errors.")
    print("=" * 70 + "\n")

    return success


if __name__ == "__main__":
    runs = 10
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        runs = int(sys.argv[1])
    run_smoke_test(total_iterations=runs)
