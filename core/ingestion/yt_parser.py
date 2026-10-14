"""YouTube caption parser using yt-dlp.

Pulls manual or auto-generated English subtitle tracks (.json3/.vtt) in < 1 second
via direct in-memory HTTP requests without downloading video or audio streams.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import httpx
import yt_dlp

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.chunker import CaptionCue

PREFERRED_LANGS = ["en", "en-orig", "en-US", "en-GB"]


@dataclass
class YouTubeParseResult:
    """The outcome of parsing a YouTube video for subtitles."""

    video_id: str
    title: str
    duration_s: float
    cues: List[CaptionCue]
    has_subtitles: bool
    track_type: str  # 'manual', 'automatic', or 'none'
    latency_ms: float


def parse_json3_captions(raw_json: dict) -> List[CaptionCue]:
    """Parses YouTube's native json3 timedtext format into CaptionCue objects."""
    cues: List[CaptionCue] = []
    events = raw_json.get("events", [])

    for event in events:
        segs = event.get("segs", [])
        if not segs:
            continue

        text = "".join(seg.get("utf8", "") for seg in segs).strip()
        # Skip pure whitespace or control characters
        if not text or text == "\n":
            continue

        start_s = event.get("tStartMs", 0) / 1000.0
        duration_s = event.get("dDurationMs", 0) / 1000.0
        end_s = start_s + duration_s

        cues.append(
            CaptionCue(
                start_s=round(start_s, 2),
                end_s=round(end_s, 2),
                text=text,
            )
        )

    return cues


def parse_vtt_timestamp(ts: str) -> float:
    """Converts a WebVTT timestamp (HH:MM:SS.mmm or MM:SS.mmm) to total seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    return float(ts)


def parse_vtt_captions(vtt_text: str) -> List[CaptionCue]:
    """Parses WebVTT subtitle text into CaptionCue objects."""
    cues: List[CaptionCue] = []
    lines = vtt_text.splitlines()

    time_pattern = re.compile(
        r"((?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})"
    )

    current_start = 0.0
    current_end = 0.0
    current_text_lines: List[str] = []

    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("WEBVTT") or line_s.isdigit():
            continue

        match = time_pattern.search(line_s)
        if match:
            # Commit previous cue if accumulated
            if current_text_lines:
                cues.append(
                    CaptionCue(
                        start_s=round(current_start, 2),
                        end_s=round(current_end, 2),
                        text=" ".join(current_text_lines),
                    )
                )
                current_text_lines = []

            current_start = parse_vtt_timestamp(match.group(1))
            current_end = parse_vtt_timestamp(match.group(2))
        else:
            # Strip inline WebVTT tags like <c.color> or <00:03.100>
            clean_line = re.sub(r"<[^>]+>", "", line_s).strip()
            if clean_line:
                current_text_lines.append(clean_line)

    if current_text_lines:
        cues.append(
            CaptionCue(
                start_s=round(current_start, 2),
                end_s=round(current_end, 2),
                text=" ".join(current_text_lines),
            )
        )

    return cues


class YouTubeCaptionParser:
    """Extracts YouTube subtitles directly via yt-dlp metadata inspection."""

    def __init__(self):
        self.ydl_opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": PREFERRED_LANGS,
            "subtitlesformat": "json3/vtt",
            "quiet": True,
            "no_warnings": True,
        }

    def _select_caption_track(self, info: dict) -> Tuple[Optional[str], str, str]:
        """Selects the best available English caption track URL and format.
        
        Returns (track_url, track_type, format_ext).
        Priority: Manual Subtitles ('en') > Auto-generated ('en-orig'/'en').
        """
        # 1. Check manual creator-uploaded subtitles
        subtitles = info.get("subtitles") or {}
        for lang in PREFERRED_LANGS:
            if lang in subtitles:
                formats = subtitles[lang]
                for fmt in formats:
                    if fmt.get("ext") in ("json3", "vtt"):
                        return fmt.get("url"), "manual", fmt.get("ext")

        # 2. Check automatic ASR subtitles
        auto_subs = info.get("automatic_captions") or {}
        for lang in PREFERRED_LANGS:
            if lang in auto_subs:
                formats = auto_subs[lang]
                for fmt in formats:
                    if fmt.get("ext") in ("json3", "vtt"):
                        return fmt.get("url"), "automatic", fmt.get("ext")

        return None, "none", ""

    def parse(self, video_url: str) -> YouTubeParseResult:
        """Inspects video URL, pulls subtitles, and returns normalized cues."""
        t_start = time.perf_counter_ns()

        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)
            except Exception as e:
                t_end = time.perf_counter_ns()
                return YouTubeParseResult(
                    video_id=video_url,
                    title="Unknown",
                    duration_s=0.0,
                    cues=[],
                    has_subtitles=False,
                    track_type="none",
                    latency_ms=(t_end - t_start) / 1_000_000.0,
                )

        video_id = info.get("id", "")
        title = info.get("title", "Unknown Title")
        duration_s = float(info.get("duration", 0.0))

        track_url, track_type, fmt_ext = self._select_caption_track(info)

        if not track_url:
            t_end = time.perf_counter_ns()
            return YouTubeParseResult(
                video_id=video_id,
                title=title,
                duration_s=duration_s,
                cues=[],
                has_subtitles=False,
                track_type="none",
                latency_ms=(t_end - t_start) / 1_000_000.0,
            )

        # Download caption payload directly in memory via HTTP GET (< 500ms)
        cues: List[CaptionCue] = []
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(track_url)
                res.raise_for_status()

                if fmt_ext == "json3":
                    cues = parse_json3_captions(res.json())
                else:
                    cues = parse_vtt_captions(res.text)
        except Exception:
            cues = []

        t_end = time.perf_counter_ns()
        latency_ms = (t_end - t_start) / 1_000_000.0

        return YouTubeParseResult(
            video_id=video_id,
            title=title,
            duration_s=duration_s,
            cues=cues,
            has_subtitles=len(cues) > 0,
            track_type=track_type,
            latency_ms=latency_ms,
        )


if __name__ == "__main__":
    # Smoke test on a short video or test query
    import argparse

    parser = argparse.ArgumentParser(description="Test YouTube direct caption parser")
    parser.add_argument("url", type=str, help="YouTube video URL")
    args = parser.parse_args()

    parser_obj = YouTubeCaptionParser()
    print(f"Inspecting URL: {args.url} ...")
    result = parser_obj.parse(args.url)

    print("\n" + "=" * 60)
    print(f"Title:         {result.title}")
    print(f"Video ID:      {result.video_id}")
    print(f"Duration:      {result.duration_s}s")
    print(f"Has Captions:  {result.has_subtitles} ({result.track_type})")
    print(f"Total Cues:    {len(result.cues)}")
    print(f"Latency:       {result.latency_ms:.2f} ms")
    print("=" * 60)

    if result.cues:
        print("\nSample First 3 Cues:")
        for c in result.cues[:3]:
            print(f"  [{c.start_s:.2f} -> {c.end_s:.2f}] \"{c.text}\"")
