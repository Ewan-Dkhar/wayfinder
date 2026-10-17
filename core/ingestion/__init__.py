"""Wayfinder Ingestion Pipeline Package.

Provides multi-source ingestion:
- YouTube subtitle extractor (yt_parser.py)
- Steam Community Guide parser (steam_parser.py)
- Web Wiki & Guide parser (wiki_parser.py)
- Sliding window and section chunking (chunker.py)
- Whisper audio fallback worker (transcriber.py)
"""

from core.ingestion.chunker import CaptionCue, IngestChunk, chunk_cues_sliding_window, chunk_text_by_sections
from core.ingestion.clipper import (
    ClipMetadata,
    VideoClipper,
    get_clips_dir,
    get_relative_clip_path,
    is_ffmpeg_available,
    resolve_clip_path,
)
from core.ingestion.steam_parser import SteamGuideParser, SteamParseResult
from core.ingestion.wiki_parser import WikiGuideParser, WikiParseResult, extract_metadata_from_url, is_safe_url
from core.ingestion.yt_parser import YouTubeCaptionParser

__all__ = [
    "CaptionCue",
    "IngestChunk",
    "chunk_cues_sliding_window",
    "chunk_text_by_sections",
    "ClipMetadata",
    "VideoClipper",
    "get_clips_dir",
    "get_relative_clip_path",
    "is_ffmpeg_available",
    "resolve_clip_path",
    "SteamGuideParser",
    "SteamParseResult",
    "WikiGuideParser",
    "WikiParseResult",
    "extract_metadata_from_url",
    "is_safe_url",
    "YouTubeCaptionParser",
]
