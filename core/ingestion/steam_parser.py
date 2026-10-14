"""Steam Community Guide and written documentation parser.

Fetches and cleans Steam Community Guides and local Markdown files,
converting BBCode/HTML sections into atomic, high-signal combat chunks.
"""

from __future__ import annotations

import html
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import httpx

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.chunker import IngestChunk, chunk_text_by_sections


@dataclass
class SteamParseResult:
    """The outcome of parsing a Steam Community Guide or written document."""

    source_id: str
    title: str
    chunks: List[IngestChunk]
    section_count: int
    latency_ms: float


def clean_steam_bbcode_and_html(raw_content: str) -> str:
    """Strips Steam BBCode tags and HTML markup, leaving pristine readable guide text."""
    # Unescape HTML entities (&amp;, &lt;, &gt;, &#39;, &quot;)
    text = html.unescape(raw_content)

    # Convert line breaks and paragraph breaks
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)

    # Convert lists: [*] item -> - item
    text = re.sub(r"\[\*\]", "\n- ", text)
    text = re.sub(r"<li>", "\n- ", text, flags=re.IGNORECASE)

    # Strip image tags: [img]...[/img] or <img ...>
    text = re.sub(r"\[img\](.*?)\[/img\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*>", "", text, flags=re.IGNORECASE)

    # Strip URL tags keeping anchor text: [url=...](text)[/url] or <a href="...">text</a>
    text = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text, flags=re.IGNORECASE)

    # Convert headers: [h1]Title[/h1] -> # Title
    text = re.sub(r"\[h1\](.*?)\[/h1\]", r"\n# \1\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\[h2\](.*?)\[/h2\]", r"\n## \1\n", text, flags=re.IGNORECASE)
    text = re.sub(r"\[h3\](.*?)\[/h3\]", r"\n### \1\n", text, flags=re.IGNORECASE)

    # Strip bold, underline, italic, code tags but keep inner text
    text = re.sub(r"\[/?(?:b|u|i|strike|code|spoiler|quote)\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:b|strong|em|i|u|span|p|ul|ol|li)[^>]*>", "", text, flags=re.IGNORECASE)

    # Strip any remaining generic HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Normalize excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class SteamGuideParser:
    """Parses Steam Community Guides via public web endpoints or local files."""

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

    def parse_url(self, url: str) -> SteamParseResult:
        """Fetches and parses a Steam Community Guide URL."""
        t_start = time.perf_counter_ns()

        # Extract guide ID from URL
        match = re.search(r"id=(\d+)", url)
        guide_id = match.group(1) if match else "steam_guide"

        try:
            with httpx.Client(timeout=10.0, headers=self.headers, follow_redirects=True) as client:
                res = client.get(url)
                res.raise_for_status()
                html_body = res.text
        except Exception as e:
            t_end = time.perf_counter_ns()
            return SteamParseResult(
                source_id=guide_id,
                title="Failed to fetch",
                chunks=[],
                section_count=0,
                latency_ms=(t_end - t_start) / 1_000_000.0,
            )

        # Extract guide title
        title_match = re.search(r'<div class="workshopItemTitle">(.*?)</div>', html_body, re.DOTALL)
        guide_title = clean_steam_bbcode_and_html(title_match.group(1)) if title_match else "Steam Community Guide"

        # Extract sections: <div class="subSection"> ... <div class="subSectionTitle"> ... </div> ... <div class="subSectionDesc"> ... </div>
        section_pattern = re.compile(
            r'<div class="subSectionTitle">\s*(.*?)\s*</div>.*?<div class="subSectionDesc">\s*(.*?)\s*</div>',
            re.DOTALL,
        )

        sections: List[Tuple[str, str]] = []
        for s_match in section_pattern.finditer(html_body):
            sec_title = clean_steam_bbcode_and_html(s_match.group(1))
            sec_desc = clean_steam_bbcode_and_html(s_match.group(2))
            if sec_desc:
                sections.append((sec_title, sec_desc))

        chunks: List[IngestChunk] = []
        for sec_title, sec_body in sections:
            formatted = f"# {sec_title}\n{sec_body}"
            sub_chunks = chunk_text_by_sections(formatted, default_title=sec_title)
            chunks.extend(sub_chunks)

        t_end = time.perf_counter_ns()
        latency_ms = (t_end - t_start) / 1_000_000.0

        return SteamParseResult(
            source_id=f"steam_{guide_id}",
            title=guide_title,
            chunks=chunks,
            section_count=len(sections),
            latency_ms=latency_ms,
        )

    def parse_markdown_file(self, file_path: Path | str) -> SteamParseResult:
        """Parses a local Markdown guide file."""
        t_start = time.perf_counter_ns()
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")

        title = path.stem.replace("_", " ").title()
        chunks = chunk_text_by_sections(content, default_title=title)

        t_end = time.perf_counter_ns()
        return SteamParseResult(
            source_id=f"local_{path.stem}",
            title=title,
            chunks=chunks,
            section_count=len(chunks),
            latency_ms=(t_end - t_start) / 1_000_000.0,
        )
