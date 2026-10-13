"""Tactical Synthesizer bridging Phase 1 (FTS5 retrieval) with Phase 2 (Local SLM).

Provides end-to-end combat distillation with defensive 3-tier JSON parsing
and a zero-crash deterministic fallback for live gameplay resilience.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# Allow running directly
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db.database import DEFAULT_DB_PATH
from core.db.fts_engine import FTSEngine, SearchResult
from core.llm.client import (
    LLMClientError,
    LLMConnectionError,
    LLMTimeoutError,
    LocalLLMClient,
)
from core.llm.prompts import FEW_SHOT_DEMO, SYSTEM_PROMPT, build_user_prompt
from core.llm.schemas import TacticalCard, TacticalCue


def parse_tactical_json(raw_text: str) -> TacticalCard:
    """Defensively parses raw LLM text into a validated TacticalCard.
    
    1. Direct Pydantic validation
    2. Markdown codeblock stripping (```json ... ```)
    3. Outermost regex JSON block extraction ({ ... })
    """
    clean_text = raw_text.strip()

    # Tier 1: Direct validation
    try:
        return TacticalCard.model_validate_json(clean_text)
    except Exception:
        pass

    # Tier 2: Strip markdown code fences
    if "```" in clean_text:
        stripped = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.MULTILINE)
        stripped = re.sub(r"\s*```$", "", stripped, flags=re.MULTILINE).strip()
        try:
            return TacticalCard.model_validate_json(stripped)
        except Exception:
            pass

    # Tier 3: Regex extract outermost JSON block
    match = re.search(r"(\{.*\})", clean_text, flags=re.DOTALL)
    if match:
        extracted = match.group(1).strip()
        return TacticalCard.model_validate_json(extracted)

    raise ValueError(f"Could not parse valid TacticalCard JSON from: {raw_text[:100]}...")


def build_fallback_card(result: SearchResult, query: str) -> TacticalCard:
    """Deterministic fallback: Extracts a valid TacticalCard from raw search text.
    
    Ensures the HUD never crashes even if the local LLM is offline or timed out.
    """
    # Create a concise summary from the first sentence
    sentences = re.split(r"(?<=[.!?])\s+", result.content_text.strip())
    summary = sentences[0] if sentences else result.content_text[:80]
    if len(summary.split()) > 20:
        summary = " ".join(summary.split()[:20]) + "..."

    # Form a sensible tactical cue from the matching text
    cue = TacticalCue(
        tell=f"Boss attack matching: '{query}'",
        action=sentences[1] if len(sentences) > 1 else "Deflect or counter in rhythm",
        outcome="Avoid damage and gain posture punish window",
    )

    return TacticalCard(
        game=result.game_id,
        encounter=result.encounter_id.replace("_", " ").title(),
        phase_or_area="Relevant Phase",
        summary=summary,
        tactical_cues=[cue],
        key_setup=[],
        source_type=result.source_type,
        source_ref=result.source_ref,
        timestamp_display=result.formatted_timestamp if result.source_type == "youtube" else None,
    )


class TacticalSynthesizer:
    """Coordinates retrieval and local SLM distillation into TacticalCards."""

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        llm_client: Optional[LocalLLMClient] = None,
    ):
        self.fts_engine = FTSEngine(db_path=db_path)
        self.llm_client = llm_client or LocalLLMClient()

    def query(
        self,
        player_query: str,
        game_id: str = "sekiro",
        encounter_id: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> Tuple[Optional[TacticalCard], dict]:
        """Executes full pipeline: FTS5 retrieval -> SLM synthesis -> TacticalCard.
        
        Returns (TacticalCard, telemetry_stats).
        """
        telemetry = {
            "query": player_query,
            "game_id": game_id,
            "retrieval_ms": 0.0,
            "synthesis_ms": 0.0,
            "total_ms": 0.0,
            "source_type": None,
            "fallback_used": False,
            "error": None,
        }

        t_total_start = time.perf_counter_ns()

        # Step 1: Retrieval (Phase 1)
        results = self.fts_engine.search(
            query=player_query,
            game_id=game_id,
            encounter_id=encounter_id,
            source_type=source_type,
            limit=1,
        )

        if not results:
            telemetry["total_ms"] = (time.perf_counter_ns() - t_total_start) / 1_000_000.0
            return None, telemetry

        top_result = results[0]
        telemetry["retrieval_ms"] = top_result.latency_ms
        telemetry["source_type"] = top_result.source_type

        # Step 2: Synthesis (Phase 2)
        system_content = f"{SYSTEM_PROMPT}\n{FEW_SHOT_DEMO}"
        user_content = build_user_prompt(
            game_id=top_result.game_id,
            encounter_id=top_result.encounter_id,
            query=player_query,
            content_text=top_result.content_text,
            source_type=top_result.source_type,
            timestamp_display=top_result.formatted_timestamp,
        )

        t_synth_start = time.perf_counter_ns()
        try:
            raw_json = self.llm_client.generate_json(
                system_prompt=system_content,
                user_prompt=user_content,
            )
            card = parse_tactical_json(raw_json)
            # Annotate with verified metadata
            card.source_type = top_result.source_type
            card.source_ref = top_result.source_ref
            if top_result.source_type == "youtube":
                card.timestamp_display = top_result.formatted_timestamp

        except (LLMClientError, ValueError) as err:
            # Defensive fallback triggered
            telemetry["fallback_used"] = True
            telemetry["error"] = str(err)
            card = build_fallback_card(top_result, player_query)

        telemetry["synthesis_ms"] = (time.perf_counter_ns() - t_synth_start) / 1_000_000.0
        telemetry["total_ms"] = (time.perf_counter_ns() - t_total_start) / 1_000_000.0

        return card, telemetry

    def close(self) -> None:
        """Cleans up database resources."""
        self.fts_engine.close()


def main() -> None:
    """CLI runner and smoke test for Phase 2 synthesis."""
    import argparse

    parser = argparse.ArgumentParser(description="Wayfinder Tactical Synthesizer CLI")
    parser.add_argument("query", type=str, default="How to counter Genichiro lightning?", nargs="?", help="Player combat query")
    parser.add_argument("--game", type=str, default="sekiro", help="Target game (default: sekiro)")
    parser.add_argument("--source", type=str, default=None, help="Optional source filter ('youtube', 'steam')")
    parser.add_argument("--test-runs", type=int, default=1, help="Number of benchmark test runs")
    args = parser.parse_args()

    synthesizer = TacticalSynthesizer()

    print("\n" + "=" * 70)
    print(f"🎮 PLAYER QUERY: '{args.query}' | GAME: '{args.game}'")
    print("=" * 70)

    # Health check for local model
    is_ollama_live = synthesizer.llm_client.check_health()
    if is_ollama_live:
        print(f"🤖 LLM Daemon: CONNECTED ({synthesizer.llm_client.base_url} -> {synthesizer.llm_client.model})")
    else:
        print(f"⚠️  LLM Daemon: NOT RUNNING on {synthesizer.llm_client.base_url}")
        print("   -> Using resilient deterministic fallback synthesizer.")

    card, telemetry = synthesizer.query(
        player_query=args.query,
        game_id=args.game,
        source_type=args.source,
    )

    if not card:
        print("\n❌ No guidance found for query.")
        return

    print("\n" + "-" * 70)
    print("📋 SYNTHESIZED TACTICAL CARD:")
    print("-" * 70)
    print(f"Boss:        {card.encounter.upper()} [{card.phase_or_area}]")
    print(f"Summary:     {card.summary}")
    print(f"Source:      {card.source_type.title()} ({card.source_ref})" + (f" @ {card.timestamp_display}" if card.timestamp_display else ""))
    print("\nCombat Cues:")
    for i, cue in enumerate(card.tactical_cues, start=1):
        print(f"  [{i}] TELL:    {cue.tell}")
        print(f"      ACTION:  {cue.action}")
        print(f"      OUTCOME: {cue.outcome}")
    if card.key_setup:
        print(f"\nKey Setup:   {', '.join(card.key_setup)}")

    print("\n" + "-" * 70)
    print("⏱️  LATENCY PROFILING:")
    print(f"   • BM25 Retrieval:  {telemetry['retrieval_ms']:.3f} ms")
    print(f"   • SLM Synthesis:   {telemetry['synthesis_ms']:.3f} ms")
    print(f"   • Total Pipeline:  {telemetry['total_ms']:.3f} ms")
    print(f"   • Fallback Used:   {telemetry['fallback_used']}")
    print("=" * 70 + "\n")

    synthesizer.close()


if __name__ == "__main__":
    main()
