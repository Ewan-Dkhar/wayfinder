"""Prompt templates and few-shot formatting for Wayfinder tactical extraction."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are Wayfinder, an ultra-fast tactical combat distillation engine for an in-game HUD.
Your sole job is to transform messy gaming transcripts and walkthrough excerpts into strict, glanceable combat cards.

CORE RULES:
1. Strip all filler: Ignore streamer intros, subscribe calls, banter, sponsors, and personal anecdotes.
2. Grounding invariant: Only extract combat tells and actions mentioned in the text. Never hallucinate mechanics.
3. Combat cue structure: Every cue MUST follow the triple:
   - "tell": The enemy's visual/audio telegraph (animation, posture, kanji, audio cue).
   - "action": Precise player input or maneuver (timing, direction, button, counter).
   - "outcome": Combat reward or hazard avoided (stagger, posture damage, stun).
4. Strictly 1 to 3 cues maximum. Keep total card under 50 words.
5. Output STRICT JSON ONLY. Do NOT wrap in markdown fences (no ```json). Do NOT add conversational banter.
"""

FEW_SHOT_DEMO = """
[EXAMPLE INPUT]
Game: sekiro
Encounter: guardian_ape
Player Query: How to dodge the terror scream?
Source: youtube (2:25 - 3:08)
Text: "In phase two when he becomes the Headless Ape, the most dangerous move is the bloody terror roar. You can see him draw his severed head to his bloody neck stump. The second you see this tell, sprint directly away. Do NOT try to deflect the roar because the terror status effect bypasses your guard and will kill you instantly. If you get caught, use the Phoenix's Lilac Umbrella prosthetic to block all terror damage."

[EXAMPLE OUTPUT JSON]
{
  "game": "sekiro",
  "encounter": "Guardian Ape",
  "phase_or_area": "Phase 2 (Headless)",
  "summary": "Sprint away on neck draw or block with Phoenix Umbrella.",
  "tactical_cues": [
    {
      "tell": "Draws severed head to bloody neck stump",
      "action": "Sprint backward immediately OR deploy Phoenix's Lilac Umbrella",
      "outcome": "Avoids fatal unblockable Terror status buildup"
    }
  ],
  "key_setup": ["Phoenix's Lilac Umbrella"]
}
"""


def build_user_prompt(
    game_id: str,
    encounter_id: str,
    query: str,
    content_text: str,
    source_type: str = "youtube",
    timestamp_display: str | None = None,
) -> str:
    """Constructs the prompt payload for the local SLM."""
    time_info = f" ({timestamp_display})" if timestamp_display else ""
    return f"""Synthesize this guide excerpt into a single TacticalCard JSON object.

[INPUT]
Game: {game_id}
Encounter: {encounter_id}
Player Query: {query}
Source: {source_type}{time_info}
Text: "{content_text.strip()}"

[OUTPUT JSON]
"""
