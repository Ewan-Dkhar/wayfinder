"""Deterministic seed data for Sekiro: Shadows Die Twice.

Provides realistic, timestamped YouTube transcript segments covering major combat mechanics
for Genichiro Ashina (Ashina Castle) and Guardian Ape (Sunken Valley).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

# Allow running directly as 'python3 core/db/seeds/sekiro_seed.py'
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db.database import (
    DEFAULT_DB_PATH,
    GuideChunk,
    get_connection,
    init_db,
    insert_chunks_batch,
)

SEKIRO_CHUNKS: List[GuideChunk] = [
    # ---------------------------------------------------------
    # Genichiro Ashina — Ashina Castle (Phase 1, 2, 3)
    # ---------------------------------------------------------
    GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        video_id="yt_genichiro_mastery_01",
        start_time=45.0,
        end_time=78.5,
        transcript_text=(
            "Alright guys, for Genichiro's first phase, watch out for his jumping downward slam. "
            "Immediately after the slam, the dangerous red kanji flashes on screen for a perilous thrust attack. "
            "Do NOT try to roll sideways. Instead, perform a forward Mikiri Counter right into his spear tip "
            "to deal massive posture damage and immediately reset the combat rhythm."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        video_id="yt_genichiro_mastery_01",
        start_time=82.0,
        end_time=115.0,
        transcript_text=(
            "Now in phase two, after his jump slam, Genichiro can mix it up. Instead of a thrust, "
            "he often spins around for a perilous sweep attack. Look closely at his body posture: "
            "if he turns sideways with a white glint near the floor, jump straight up over the blade "
            "and press jump again while in the air to head-stomp him for heavy posture buildup."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        video_id="yt_genichiro_mastery_01",
        start_time=130.0,
        end_time=168.0,
        transcript_text=(
            "When you create distance or try to drink your Healing Gourd, Genichiro pulls out his giant bow. "
            "He will fire a rapid four-arrow flurry followed by a delayed heavy shot. "
            "You can deflect the first three arrows in rhythm, but dodge roll forward on the fourth shot "
            "to close the gap and punish his recovery animation."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        video_id="yt_genichiro_mastery_01",
        start_time=210.0,
        end_time=255.0,
        transcript_text=(
            "In phase three, Way of Tomoe, he gains electric attacks. When he leaps high into the air surrounded "
            "by electricity for the lightning reversal attack, do NOT panic roll on the ground. "
            "Wait a split second, jump straight up into the air to absorb the lightning, and spam your standard attack button "
            "before landing on the ground. This reflects the lightning reversal directly back into Genichiro, "
            "stunning him for five full seconds and wiping a third of his health bar."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="genichiro",
        video_id="yt_genichiro_mastery_01",
        start_time=260.0,
        end_time=292.0,
        transcript_text=(
            "Also in Tomoe phase, he opens the fight with a lunging shadow thrust across the entire arena. "
            "As soon as the cutscene ends, do not move left or right. Just stand your ground and tap dodge forward "
            "the moment the red kanji symbol fades to land a guaranteed free Mikiri Counter."
        ),
    ),

    # ---------------------------------------------------------
    # Guardian Ape — Sunken Valley (Phase 1 & Phase 2 Headless)
    # ---------------------------------------------------------
    GuideChunk(
        game_id="sekiro",
        encounter_id="guardian_ape",
        video_id="yt_guardian_ape_breakdown_02",
        start_time=30.0,
        end_time=65.0,
        transcript_text=(
            "During Guardian Ape phase one, whenever he reaches behind his backside, he is preparing his toxic dung toss. "
            "He leaps high backwards into the air and hurls poop directly at you. The easiest counter is to sprint "
            "directly towards and underneath him while he is in the air. The dung will fly completely over your head, "
            "leaving his back exposed for 3 to 4 free hits."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="guardian_ape",
        video_id="yt_guardian_ape_breakdown_02",
        start_time=70.0,
        end_time=102.0,
        transcript_text=(
            "If Guardian Ape rolls onto his back and starts flailing his arms and legs in a temper tantrum, "
            "stand right next to his head and deflect the strikes in rhythm. Alternatively, equip the Firecracker prosthetic "
            "to stun him for several seconds, but remember there is an internal cooldown before Firecrackers can stagger him again."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="guardian_ape",
        video_id="yt_guardian_ape_breakdown_02",
        start_time=145.0,
        end_time=188.0,
        transcript_text=(
            "In phase two when he becomes the Headless Ape, the most dangerous move is the bloody terror roar. "
            "You can see him draw his severed head to his bloody neck stump. The second you see this tell, sprint directly away. "
            "Do NOT try to deflect the roar because the terror status effect bypasses your guard and will kill you instantly. "
            "If you get caught, use the Phoenix's Lilac Umbrella prosthetic to block all terror damage."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="guardian_ape",
        video_id="yt_guardian_ape_breakdown_02",
        start_time=195.0,
        end_time=235.0,
        transcript_text=(
            "The key opening in the headless phase is his towering sword slam. He will snake his body upright, "
            "pause at maximum height, and bring the massive katana straight down. If you deflect this single heavy slam cleanly, "
            "the ape collapses forward into a massive stagger. Immediately double-tap the Loaded Spear prosthetic into his neck cavity "
            "to pull out the centipede parasite for catastrophic posture damage."
        ),
    ),
    GuideChunk(
        game_id="sekiro",
        encounter_id="guardian_ape",
        video_id="yt_guardian_ape_breakdown_02",
        start_time=240.0,
        end_time=275.0,
        transcript_text=(
            "For his sliding dive sweep, the ape runs away and then slides belly-first across the snow sweeping his katana. "
            "Simply jump straight over the incoming blade and land with a mid-air combat art or jumping slash. "
            "It's one of his easiest attacks to anticipate."
        ),
    ),
]


def seed_sekiro(db_path: Path | str | None = None, reset: bool = False) -> int:
    """Populates the database with Sekiro seed chunks.
    
    Initializes tables if they do not exist, and inserts all SEKIRO_CHUNKS in a single transaction.
    If reset=True, deletes existing Sekiro chunks before inserting.
    """
    target_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    init_db(target_path)
    conn = get_connection(target_path)

    with conn:
        if reset:
            print("[Seed] Resetting Sekiro chunks...")
            conn.execute("DELETE FROM guide_chunks WHERE game_id = 'sekiro'")

        # Check if already seeded to avoid duplicates
        cur = conn.execute("SELECT COUNT(*) AS count FROM guide_chunks WHERE game_id = 'sekiro'")
        existing = cur.fetchone()["count"]
        if existing > 0:
            print(f"[Seed] Sekiro already seeded ({existing} chunks present). Skipping insert.")
            return existing

        count = insert_chunks_batch(conn, SEKIRO_CHUNKS)
        print(f"[Seed] Successfully seeded {count} Sekiro chunks.")
        return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Sekiro combat guide transcripts into Wayfinder DB")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite database")
    parser.add_argument("--reset", action="store_true", help="Delete existing Sekiro chunks and re-seed")
    args = parser.parse_args()

    seed_sekiro(db_path=args.db, reset=args.reset)
