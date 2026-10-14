"""Universal chunking algorithms for Wayfinder ingestion.

Provides two distinct chunking strategies:
1. Time-based sliding window chunker for continuous speech transcripts (YouTube/Whisper)
   with overlapping stride to preserve combat context across cutoffs.
2. Section/Heading-based chunker for structured written guides (Steam Community / Markdown).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence


@dataclass(frozen=True)
class CaptionCue:
    """Represents an atomic timestamped subtitle or transcription cue."""

    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class IngestChunk:
    """A normalized chunk ready to be inserted into guide_chunks."""

    start_time: float
    end_time: float
    content_text: str


def deduplicate_cue_text(cues: Sequence[CaptionCue]) -> str:
    """Cleans and deduplicates rolling ASR speech segments into fluent prose.
    
    YouTube auto-captions often duplicate consecutive words across adjacent cues.
    This stitches cues together without stuttering repetitions.
    """
    cleaned_tokens: List[str] = []

    for cue in cues:
        raw = cue.text.strip()
        if not raw:
            continue

        # Split into words
        words = raw.split()
        for word in words:
            # Skip if identical to the immediately preceding word (common in ASR loops)
            if cleaned_tokens and word.lower() == cleaned_tokens[-1].lower():
                continue
            cleaned_tokens.append(word)

    return " ".join(cleaned_tokens)


def chunk_cues_sliding_window(
    cues: Sequence[CaptionCue],
    window_seconds: float = 35.0,
    stride_seconds: float = 15.0,
    min_words: int = 8,
) -> List[IngestChunk]:
    """Slices a timeline of caption cues into overlapping combat windows.

    Parameters:
    - window_seconds: Total span of each chunk (35-45s captures a full attack/counter loop).
    - stride_seconds: Step size between window starts (15s overlap ensures no mechanic is cut in half).
    - min_words: Discards empty or trivial filler windows.
    """
    if not cues:
        return []

    max_time = cues[-1].end_s
    chunks: List[IngestChunk] = []
    window_start = cues[0].start_s

    while window_start < max_time:
        window_end = window_start + window_seconds

        # Find all cues that overlap with this window [window_start, window_end]
        overlapping_cues = [
            c for c in cues if (c.start_s < window_end and c.end_s > window_start)
        ]

        if overlapping_cues:
            merged_text = deduplicate_cue_text(overlapping_cues)
            words = merged_text.split()

            if len(words) >= min_words:
                chunks.append(
                    IngestChunk(
                        start_time=round(window_start, 1),
                        end_time=round(window_end, 1),
                        content_text=merged_text,
                    )
                )

        window_start += stride_seconds

    return chunks


def chunk_text_by_sections(
    raw_text: str,
    default_title: str = "Guide Section",
    max_words_per_chunk: int = 250,
) -> List[IngestChunk]:
    """Splits structured written guides (Markdown or Steam BBCode) by headings.
    
    Creates atomic, high-signal chunks matching specific boss phases or attacks.
    """
    # Regex matching Markdown headers (#, ##, ###) or Steam BBCode [h1], [h2], [h3]
    heading_pattern = re.compile(
        r"(?:^#{1,3}\s+(.+)$)|(?:\[h[1-3]\](.*?)\[/h[1-3]\])",
        re.MULTILINE | re.IGNORECASE,
    )

    splits = []
    last_idx = 0
    current_heading = default_title

    for match in heading_pattern.finditer(raw_text):
        start_idx = match.start()
        # Save previous section if it has content
        if start_idx > last_idx:
            section_body = raw_text[last_idx:start_idx].strip()
            if section_body:
                splits.append((current_heading, section_body))

        # Update heading (match group 1 is Markdown, group 2 is Steam BBCode)
        current_heading = (match.group(1) or match.group(2) or default_title).strip()
        last_idx = match.end()

    # Append the final trailing section
    if last_idx < len(raw_text):
        tail = raw_text[last_idx:].strip()
        if tail:
            splits.append((current_heading, tail))

    if not splits:
        # No headings found, treat entire text as one section
        splits = [(default_title, raw_text.strip())]

    chunks: List[IngestChunk] = []

    for heading, body in splits:
        words = body.split()
        if len(words) <= max_words_per_chunk:
            combined = f"[{heading.upper()}]\n{body}"
            chunks.append(
                IngestChunk(
                    start_time=0.0,
                    end_time=0.0,
                    content_text=combined,
                )
            )
        else:
            # Paragraph chunking for long sections
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
            cur_para: List[str] = []
            cur_count = 0

            for p in paragraphs:
                p_len = len(p.split())
                if cur_count + p_len > max_words_per_chunk and cur_para:
                    chunks.append(
                        IngestChunk(
                            start_time=0.0,
                            end_time=0.0,
                            content_text=f"[{heading.upper()}]\n" + "\n\n".join(cur_para),
                        )
                    )
                    cur_para = [p]
                    cur_count = p_len
                else:
                    cur_para.append(p)
                    cur_count += p_len

            if cur_para:
                chunks.append(
                    IngestChunk(
                        start_time=0.0,
                        end_time=0.0,
                        content_text=f"[{heading.upper()}]\n" + "\n\n".join(cur_para),
                    )
                )

    return chunks
