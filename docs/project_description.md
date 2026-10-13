# Wayfinder — Universal AI In-Game Companion

## Overview
Wayfinder is a universal in-game tactical companion designed to eliminate the friction of learning complex game mechanics. Instead of interrupting gameplay to scrub through 20-minute video walkthroughs on a secondary screen or browser window, players hit a single hotkey (`Alt + G`) to summon a translucent tactical HUD directly over their active game.

Wayfinder ingests walkthrough footage, strips conversational filler, indexes timestamped combat cues via local BM25 full-text search, and passes relevant segments through a quantized local language model (Llama 3.2 3B). The model synthesizes a schema-enforced cheat sheet highlighting enemy visual cues, dodge/parry execution, and punish windows.

## Why Open-Source AI Matters
1. **Zero Marginal Operating Cost:** Cloud multimodal and transcription APIs make indexing hours of gameplay video cost-prohibitive. Wayfinder uses `faster-whisper` and open-weight SLMs on the user's local machine, keeping video processing completely free.
2. **Deterministic Latency:** Remote API round trips introduce lag and break during network drops. Local inference guarantees tactical cards render in under 1.5 seconds.
3. **Strict Schema Adherence:** Open weights combined with local grammar constraints (GBNF) force the model to output strict UI card structures without conversational fluff.

## The Business Angle ("Side Hustle" Viability)
- **The Opportunity:** Gamers resist recurring SaaS subscriptions for plain text wikis, but multi-million-dollar companion apps (Overwolf, Mobalytics) prove high willingness-to-pay for frictionless, non-intrusive HUD overlays.
- **Monetization Model:**
  - **Open Core:** Free local client, on-demand video ingestion, and user-managed game libraries.
  - **Curated Guide Packs ($9.99 Lifetime):** Pre-compiled, zero-wait tactical databases for newly released AAA titles.