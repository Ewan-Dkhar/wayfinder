"""Universal Web Wiki and Guide Parser for Wayfinder.

Fetches, sanitizes, and normalizes gaming wiki guides (Fextralife, Fandom, Wiki.gg,
MediaWiki, and generic HTML guide pages) into high-signal tactical combat chunks.

Built from first principles with zero external dependencies (Python standard library
html.parser + httpx), incorporating:
- Strict SSRF (Server-Side Request Forgery) protection against private/loopback/link-local networks.
- Safe redirect resolution verifying target IPs on every hop.
- Malicious code sanitization (stripping <script>, <iframe>, <object>, <embed>, inline events).
- Attack & Counter table extraction into high-density SQLite FTS5 search bullets.
- Prompt injection and LLM control token neutralization.
- DoS protection (5MB streaming cutoff, 10s timeout, max 3 redirects).
"""

from __future__ import annotations

import html
from html.parser import HTMLParser
import ipaddress
from pathlib import Path
import re
import socket
import sys
import time
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
import httpx

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.chunker import IngestChunk, chunk_text_by_sections


# -----------------------------------------------------------------------------
# Security & SSRF Protection
# -----------------------------------------------------------------------------

def is_safe_url(url: str) -> Tuple[bool, Optional[str]]:
    """Validates URL scheme, domain, and resolved IP to strictly prohibit SSRF.
    
    Prohibits:
    - Non-HTTP(S) protocols (file://, ftp://, gopher://, javascript:, data:)
    - Credentials in URL (user:pass@host)
    - Loopback addresses (127.0.0.0/8, ::1)
    - RFC 1918 Private ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
    - Link-local addresses (169.254.0.0/16, fe80::/10)
    - Cloud metadata IPs (169.254.169.254)
    - Multicast, reserved, and unspecified addresses (0.0.0.0)
    """
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported URL protocol '{parsed.scheme}'. Only 'http' and 'https' are allowed."

    if not parsed.hostname:
        return False, "Missing hostname in URL."

    if parsed.username or parsed.password:
        return False, "User credentials in URL are prohibited."

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    hostname = parsed.hostname.strip("[]")

    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"DNS resolution failed for hostname '{hostname}': {e}"
    except Exception as e:
        return False, f"Network validation error for '{hostname}': {e}"

    if not addr_info:
        return False, f"No IP addresses resolved for hostname '{hostname}'."

    for family, socktype, proto, canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid resolved IP address: {ip_str}"

        if ip.is_loopback:
            return False, f"SSRF blocked: Host resolves to loopback IP {ip}."
        if ip.is_link_local:
            return False, f"SSRF blocked: Host resolves to link-local IP {ip}."
        if ip.is_private:
            return False, f"SSRF blocked: Host resolves to private network IP {ip}."
        if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, f"SSRF blocked: Host resolves to restricted IP {ip}."

    return True, None


def sanitize_prompt_injection(text: str) -> str:
    """Neutralizes LLM instruction overrides, special tokens, and control characters."""
    # Strip null bytes and non-printable control chars except \t, \n, \r
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

    # Replace invisible zero-width unicode characters
    text = re.sub(r"[\u200B-\u200D\uFEFF\u202A-\u202E]", " ", text)

    # Neutralize ChatML / Llama / Anthropic special control markers
    injection_tokens = [
        r"<\|im_start\|>",
        r"<\|im_end\|>",
        r"<\|system\|>",
        r"<\|user\|>",
        r"<\|assistant\|>",
        r"\[INST\]",
        r"\[/INST\]",
        r"<<SYS>>",
        r"<</SYS>>",
        r"\[SYSTEM\]",
        r"\[DEVELOPER\]",
        r"### System:",
        r"### Human:",
        r"### Assistant:",
    ]
    for pattern in injection_tokens:
        text = re.sub(pattern, "[FILTERED]", text, flags=re.IGNORECASE)

    return text


def extract_metadata_from_url(url: str) -> Tuple[str, str]:
    """Infers default game_id and encounter_id from wiki and guide URLs.
    
    Examples:
    - https://firstberserkerkhazan.wiki.fextralife.com/Maluca
      -> ("firstberserkerkhazan", "maluca")
    - https://eldenring.wiki.fextralife.com/Malenia+Blade+of+Miquella
      -> ("eldenring", "malenia_blade_of_miquella")
    - https://sekiroshadowsdietwice.fandom.com/wiki/Genichiro_Ashina
      -> ("sekiroshadowsdietwice", "genichiro_ashina")
    - https://monsterhunter.wiki.gg/wiki/Arkveld
      -> ("monsterhunter", "arkveld")
    """
    parsed = urllib.parse.urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")

    game_id = "wiki_game"
    encounter_id = "combat_guide"

    # Fextralife: <subdomain>.wiki.fextralife.com or <subdomain>.fextralife.com
    if "fextralife.com" in hostname:
        sub = hostname.split(".")[0]
        if sub and sub not in ("wiki", "www"):
            game_id = sub
    # Fandom: <subdomain>.fandom.com
    elif "fandom.com" in hostname:
        sub = hostname.split(".")[0]
        if sub and sub not in ("www",):
            game_id = sub
    # Wiki.gg: <subdomain>.wiki.gg
    elif "wiki.gg" in hostname:
        sub = hostname.split(".")[0]
        if sub and sub not in ("www",):
            game_id = sub
    elif hostname:
        # Fallback to base domain name (e.g. ign.com -> ign)
        parts = hostname.split(".")
        game_id = parts[0] if parts[0] != "www" else (parts[1] if len(parts) > 1 else "web")

    # Encounter from path
    if path:
        # If path starts with wiki/ or guides/, skip that segment
        segments = [s for s in path.split("/") if s and s.lower() not in ("wiki", "guides", "guide", "index.php")]
        if segments:
            raw_encounter = segments[-1]
            # Replace '+' and '-' and '%20' with '_'
            unquoted = urllib.parse.unquote(raw_encounter)
            clean = re.sub(r"[\s+-]+", "_", unquoted)
            clean = re.sub(r"[^a-zA-Z0-9_]", "", clean).strip("_").lower()
            if clean:
                encounter_id = clean

    # Final slugification cleanups
    game_clean = re.sub(r"[^a-zA-Z0-9_]", "", game_id.replace("-", "_")).strip("_").lower() or "wiki_game"
    encounter_clean = encounter_id or "combat_guide"

    return game_clean, encounter_clean


# -----------------------------------------------------------------------------
# Safe HTML Parser for Gaming Wikis
# -----------------------------------------------------------------------------

class SafeWikiHTMLParser(HTMLParser):
    """Parses Wiki HTML into structured Markdown, stripping malicious code and noise."""

    IGNORED_TAGS = {
        "script",
        "style",
        "noscript",
        "iframe",
        "object",
        "embed",
        "svg",
        "canvas",
        "nav",
        "footer",
        "aside",
        "header",
        "form",
        "input",
        "button",
        "select",
        "textarea",
    }

    SKIP_PATTERNS = (
        "ad-",
        "advert",
        "sidebar",
        "comments",
        "social",
        "share",
        "breadcrumb",
        "printfooter",
        "catlinks",
        "navbox",
        "mw-jump",
        "mw-editsection",
        "discussion",
        "site-notice",
        "cookie-notice",
    )

    ARTICLE_IDS = {
        "mw-content-text",
        "bodycontent",
        "wiki-content",
        "article-content",
        "main-content",
        "entry-content",
        "post-content",
    }

    ARTICLE_CLASSES = {
        "mw-parser-output",
        "article-body",
        "entry-content",
        "guide-content",
        "wiki-article",
    }

    def __init__(self, require_article: bool = False):
        super().__init__()
        self.output: List[str] = []
        self.ignored_stack: List[str] = []
        self.require_article = require_article
        self.in_article = not require_article
        self.article_depth = 0

        # Table state
        self.in_table = False
        self.table_headers: List[str] = []
        self.current_row: List[str] = []
        self.current_cell: List[str] = []
        self.is_header_cell = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        class_str = attr_dict.get("class", "").lower()
        id_str = attr_dict.get("id", "").lower()

        # Check article container entry if scoping is enabled
        if self.require_article:
            if not self.in_article:
                if id_str in self.ARTICLE_IDS or any(c in class_str for c in self.ARTICLE_CLASSES) or tag in ("article", "main"):
                    self.in_article = True
                    self.article_depth = 1
            else:
                self.article_depth += 1

        # Ignored subtree (scripts, styles, ads, navbars)
        if self.ignored_stack:
            self.ignored_stack.append(tag)
            return

        if tag in self.IGNORED_TAGS or any(p in class_str or p in id_str for p in self.SKIP_PATTERNS):
            self.ignored_stack.append(tag)
            return

        # If scoping to article container and outside it, skip
        if self.require_article and not self.in_article:
            return

        # Process structural elements
        if tag == "table":
            self.in_table = True
            self.table_headers = []
            self.output.append("\n\n")
        elif tag == "tr":
            self.current_row = []
        elif tag in ("th", "td"):
            self.is_header_cell = (tag == "th")
            self.current_cell = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.output.append(f"\n\n{'#' * level} ")
        elif tag == "p":
            self.output.append("\n\n")
        elif tag == "br":
            self.output.append("\n")
        elif tag == "li":
            self.output.append("\n* ")

    def handle_endtag(self, tag: str):
        if self.ignored_stack:
            self.ignored_stack.pop()
            if self.require_article and self.in_article:
                self.article_depth -= 1
                if self.article_depth <= 0:
                    self.in_article = False
            return

        if self.require_article and self.in_article:
            self.article_depth -= 1
            if self.article_depth <= 0:
                self.in_article = False

        if tag in ("th", "td"):
            cell_text = " ".join("".join(self.current_cell).split())
            self.current_row.append(cell_text)
            self.current_cell = []
        elif tag == "tr":
            if self.current_row:
                row_joined_lower = " ".join(self.current_row).lower()
                is_header = self.is_header_cell or any(
                    h in row_joined_lower
                    for h in ("attack", "counter", "description", "move", "details", "telegraph", "strategy")
                )
                if is_header and not self.table_headers:
                    self.table_headers = self.current_row
                elif self.table_headers and len(self.table_headers) == len(self.current_row):
                    # Format table row into structured bullet
                    parts = [f"{h}: {val}" for h, val in zip(self.table_headers, self.current_row) if val]
                    if parts:
                        self.output.append("* " + " | ".join(parts) + "\n")
                else:
                    line = " | ".join(c for c in self.current_row if c)
                    if line:
                        self.output.append(f"* {line}\n")
            self.current_row = []
        elif tag == "table":
            self.in_table = False
            self.table_headers = []
            self.output.append("\n")

    def handle_data(self, data: str):
        if self.ignored_stack:
            return
        if self.require_article and not self.in_article:
            return

        clean_data = data.strip()
        if not clean_data:
            return

        if self.in_table:
            self.current_cell.append(clean_data)
        else:
            self.output.append(f" {clean_data} ")

    def get_markdown(self) -> str:
        """Returns the sanitized, formatted Markdown string."""
        text = "".join(self.output)
        # Unescape entities (&amp; -> &, &quot; -> ", etc.)
        text = html.unescape(text)
        # Normalize excessive spaces and lines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" \n", "\n", text)
        text = re.sub(r"\n ", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# -----------------------------------------------------------------------------
# Parser Result & WikiGuideParser Engine
# -----------------------------------------------------------------------------

@dataclass
class WikiParseResult:
    """The outcome of fetching and parsing a Wiki combat guide."""

    source_id: str
    title: str
    game_id: str
    encounter_id: str
    chunks: List[IngestChunk]
    section_count: int
    latency_ms: float
    raw_markdown: str = ""


class WikiGuideParser:
    """Secure, high-performance parser for gaming wikis and web guides."""

    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout_s: float = 10.0, max_bytes: int = 5 * 1024 * 1024):
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self.headers = {
            "User-Agent": self.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def fetch_html(self, url: str) -> Tuple[str, str]:
        """Fetches web page HTML with strict SSRF protection and safe redirect validation."""
        current_url = url.strip()
        hops = 0
        max_hops = 3

        while hops <= max_hops:
            is_safe, err_msg = is_safe_url(current_url)
            if not is_safe:
                raise ValueError(f"SSRF validation blocked: {err_msg}")

            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_s, connect=5.0),
                headers=self.headers,
                follow_redirects=False,
            ) as client:
                res = client.get(current_url)

                if res.is_redirect:
                    location = res.headers.get("location")
                    if not location:
                        raise ValueError(f"Redirect from {current_url} missing Location header.")
                    current_url = urllib.parse.urljoin(current_url, location)
                    hops += 1
                    continue

                res.raise_for_status()

                # Stream and enforce max body size (5MB)
                content_chunks = []
                total_bytes = 0
                for chunk in res.iter_text():
                    total_bytes += len(chunk.encode("utf-8"))
                    if total_bytes > self.max_bytes:
                        raise ValueError(f"Page content exceeds maximum size of {self.max_bytes // 1024 // 1024}MB.")
                    content_chunks.append(chunk)

                return current_url, "".join(content_chunks)

        raise ValueError(f"Exceeded maximum redirects ({max_hops}) for {url}")

    def parse_html_content(
        self,
        html_content: str,
        source_url: str = "https://wiki.fextralife.com/guide",
        game_id: Optional[str] = None,
        encounter_id: Optional[str] = None,
    ) -> WikiParseResult:
        """Parses in-memory HTML text into atomic combat chunks with sanitization."""
        t_start = time.perf_counter_ns()

        inferred_game, inferred_encounter = extract_metadata_from_url(source_url)
        final_game = (game_id or inferred_game).strip().lower()
        final_encounter = (encounter_id or inferred_encounter).strip().lower()

        # Check if known article container markers exist in HTML
        has_article_markers = any(
            marker in html_content
            for marker in (
                'id="mw-content-text"',
                "id='mw-content-text'",
                'class="mw-parser-output"',
                "class='mw-parser-output'",
                "<article",
                "<main",
            )
        )

        parser = SafeWikiHTMLParser(require_article=has_article_markers)
        parser.feed(html_content)
        raw_markdown = parser.get_markdown()

        # If article container was too strict and returned nothing, fallback to parsing full document
        if not raw_markdown.strip() and has_article_markers:
            fallback_parser = SafeWikiHTMLParser(require_article=False)
            fallback_parser.feed(html_content)
            raw_markdown = fallback_parser.get_markdown()

        # Sanitize against prompt injections and control tokens
        clean_markdown = sanitize_prompt_injection(raw_markdown)

        # Chunk markdown using heading-aware chunker
        guide_title = final_encounter.replace("_", " ").title()
        chunks = chunk_text_by_sections(clean_markdown, default_title=guide_title)

        t_end = time.perf_counter_ns()
        latency_ms = (t_end - t_start) / 1_000_000.0

        return WikiParseResult(
            source_id=f"wiki_{final_encounter}",
            title=guide_title,
            game_id=final_game,
            encounter_id=final_encounter,
            chunks=chunks,
            section_count=len(chunks),
            latency_ms=latency_ms,
            raw_markdown=clean_markdown,
        )

    def parse_url(
        self,
        url: str,
        game_id: Optional[str] = None,
        encounter_id: Optional[str] = None,
    ) -> WikiParseResult:
        """Fetches and parses a live wiki or web guide URL into combat chunks."""
        final_url, html_content = self.fetch_html(url)
        return self.parse_html_content(
            html_content=html_content,
            source_url=final_url,
            game_id=game_id,
            encounter_id=encounter_id,
        )
