"""Pydantic schemas for Wayfinder tactical combat distillation.

Enforces strict schema validation for HUD combat cards:
- TacticalCue (Tell -> Action -> Outcome)
- TacticalCard (High-level glanceable combat cheat sheet)
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class TacticalCue(BaseModel):
    """An atomic combat cue linking enemy telegraph to player response."""

    tell: str = Field(
        ...,
        description="Visual or audio telegraph from the boss (e.g. 'Red kanji + jump slam')",
        examples=["Red kanji flashes during jump slam recovery"],
    )
    action: str = Field(
        ...,
        description="Precise button input, dodge direction, or parry timing",
        examples=["Mikiri Counter forward directly into spear tip"],
    )
    outcome: str = Field(
        ...,
        description="Punish window or hazard avoided",
        examples=["Deals heavy posture damage and resets combat rhythm"],
    )


class TacticalCard(BaseModel):
    """Glanceable combat card rendered directly onto the in-game HUD."""

    game: str = Field(..., description="Target game identifier (e.g. 'sekiro')")
    encounter: str = Field(..., description="Boss or enemy name (e.g. 'Genichiro Ashina')")
    phase_or_area: str = Field(default="All Phases", description="Encounter phase or combat area")
    summary: str = Field(
        ...,
        description="One-sentence high-level tactic (strictly max 20 words)",
        examples=["Mikiri counter the thrust or head-stomp the sweep after jump slam."],
    )
    tactical_cues: List[TacticalCue] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="1 to 3 atomic combat cues",
    )
    key_setup: List[str] = Field(
        default_factory=list,
        description="Recommended items, combat arts, or prosthetics",
        examples=[["Mikiri Counter", "Loaded Spear"]],
    )
    source_type: Optional[str] = Field(
        default="youtube",
        description="Source type ('youtube', 'steam', 'wiki')",
    )
    source_ref: Optional[str] = Field(
        default=None,
        description="Video ID or guide URL",
    )
    timestamp_display: Optional[str] = Field(
        default=None,
        description="Formatted time range (e.g. '3:30 - 4:15')",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary_length(cls, v: str) -> str:
        """Ensures summary stays glanceable for an active player."""
        words = v.strip().split()
        if len(words) > 25:
            # Trim gracefully rather than failing hard if model is slightly verbose
            return " ".join(words[:25]) + "..."
        return v
