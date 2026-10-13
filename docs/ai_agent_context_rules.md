# Wayfinder — AI Agent Context & Implementation Guide

## Identity & Purpose
You are working on **Wayfinder**, an open-source, local-first in-game companion and guidance HUD. Wayfinder ingests gaming videos, indexes transcripts, and synthesizes 3-bullet tactical cheat sheets on demand.

## Architectural Non-Negotiables
1. **Universal Architecture, Sekiro MVP:** The schema, database, and prompt engineering must be game-agnostic (`game_id`, `encounter_id`), but test fixtures and MVP seed data are built against *Sekiro: Shadows Die Twice*.
2. **Strict Compute Isolation:** Wayfinder runs in the background of active games. Never allocate full VRAM. Use 4-bit quantized SLMs (`Llama-3.2-3B-Instruct`) and run `faster-whisper` in 8-bit mode (or pin to CPU).
3. **Subtitles First:** Always inspect YouTube subtitle tracks via `yt-dlp` before falling back to Whisper. Subtitle ingestion runs in < 1 second; Whisper audio transcription takes 15–30 seconds.
4. **Grammar Enforcement:** The synthesizer must never return freeform text. Output must strictly adhere to the `TacticalCard` JSON schema. Max 50 words per card.
5. **No Fullscreen Injection:** The overlay relies on standard OS transparency and requires games to run in Borderless Windowed mode. Do not attempt game executable memory patching or DirectX DLL injection.

## Primary Invariant Test
A search for `"lightning reversal"` with `game_id="sekiro"` must return the correct combat card in **< 1.5 seconds** when tested against the local SQLite database.