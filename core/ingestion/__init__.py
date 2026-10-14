"""Wayfinder Ingestion Pipeline Package.

Provides multi-source ingestion:
- YouTube subtitle extractor (yt_parser.py)
- Steam Community Guide parser (steam_parser.py)
- Sliding window and section chunking (chunker.py)
- Whisper audio fallback worker (transcriber.py)
"""
