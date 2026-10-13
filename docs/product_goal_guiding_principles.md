# Wayfinder — Product Goal & Guiding Principles

## 1. The North Star
> "Find the path forward in under 2 seconds: deliver actionable tactical counters and progression cues without forcing an Alt-Tab, video scrubbing, or frame drops."

## 2. Core Problem Statement
Gamers across genres encounter severe friction when hitting difficult walls:
- Video walkthroughs contain sponsor segments, repetitive intros, and meandering gameplay.
- Wiki entries and community guides force players to Alt-Tab, manage dual monitors, or parse walls of text.
- Players lose muscle memory, combat rhythm, and valuable gaming session time.

## 3. Product Vision
Wayfinder is a universal, open-source desktop gaming HUD powered by local speech extraction and compact language models. It transforms YouTube walkthroughs and gameplay videos into high-density micro-cards containing actionable cues (Tells, Counters, Punish Windows, Route Navigation).

While designed to support any game through modular video ingestion, **Sekiro: Shadows Die Twice** serves as the initial MVP benchmark to validate latency, extraction quality, and overlay ergonomics.

## 4. MVP Scope vs. Universal Roadmap

### MVP Scope (Sekiro Benchmark)
- Ingest and index core encounters (Genichiro Ashina, Guardian Ape, Sword Saint Isshin).
- Achieve a sub-2-second retrieval-to-synthesis pipeline on consumer hardware.
- Provide a transparent, always-on-top desktop HUD toggled via global hotkey (`Alt + G`).

### Universal Roadmap (Post-MVP)
- Arbitrary YouTube URL ingestion for any game title.
- Dynamic game profile switching (Elden Ring, Black Myth: Wukong, Monster Hunter).
- Pre-computed, downloadable community Guide Packs (`.pack` SQLite archives).