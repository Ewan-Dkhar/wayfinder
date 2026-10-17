"""Ahead-of-Time (AOT) Video Slicing Engine for Wayfinder.

Extracts, compresses, and normalizes short tactical combat clips (2–6s)
from YouTube guides or local gameplay captures using yt-dlp and ffmpeg.

First-Principles Design Constraints:
1. Muted audio stream (-an): Saves bandwidth and eliminates collision with in-game combat audio.
2. 480p resolution & yuv420p: Flawless hardware-accelerated playback across WebView2, WebKitGTK, and WKWebView.
3. +faststart moov atom: Enables instant, sub-millisecond playback initiation without buffering entire file.
4. Low file footprint: Target 100KB - 400KB per clip (~10MB total per complete game).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Locate OS-standard application data directory (matching core.db.database)
if sys.platform == "win32":
    APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "wayfinder"
elif sys.platform == "darwin":
    APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "wayfinder"
else:
    APP_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "wayfinder"


def get_clips_dir() -> Path:
    """Returns the directory where processed combat clips are stored.
    
    Respects WAYFINDER_CLIPS_DIR environment variable for isolated testing.
    """
    env_override = os.getenv("WAYFINDER_CLIPS_DIR")
    if env_override:
        p = Path(env_override).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    target = APP_DATA_DIR / "clips"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_relative_clip_path(game_id: str, encounter_id: str, chunk_id: int, ext: str = "mp4") -> str:
    """Generates the canonical relative path for a chunk clip."""
    clean_game = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in game_id.lower())
    clean_encounter = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in encounter_id.lower())
    return f"clips/{clean_game}/{clean_encounter}_{chunk_id}.{ext}"


def resolve_clip_path(relative_or_absolute_path: str | Path, base_dir: Optional[Path] = None) -> Path:
    """Resolves a relative clip path to an absolute filesystem Path."""
    p = Path(relative_or_absolute_path)
    if p.is_absolute():
        return p

    base = base_dir or APP_DATA_DIR
    path_str = str(relative_or_absolute_path)
    if path_str.startswith("clips/"):
        return base / path_str
    return base / "clips" / path_str


def is_ffmpeg_available(custom_bin: Optional[str] = None) -> bool:
    """Returns True if ffmpeg executable is available in PATH or at custom location."""
    target = custom_bin or "ffmpeg"
    return shutil.which(target) is not None


def is_ytdlp_available() -> bool:
    """Returns True if yt-dlp package is installed and importable."""
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass(frozen=True)
class ClipMetadata:
    """Metadata for an indexed video clip asset."""

    chunk_id: int
    relative_path: str
    absolute_path: Path
    start_s: float
    end_s: float
    duration_s: float
    file_size_bytes: int
    format: str = "mp4"


class VideoClipper:
    """Coordinates ahead-of-time slicing and hardware-optimized encoding for combat cues."""

    def __init__(
        self,
        clips_dir: Optional[Path] = None,
        ffmpeg_bin: Optional[str] = None,
    ):
        self.clips_dir = clips_dir or get_clips_dir()
        self.ffmpeg_bin = ffmpeg_bin or "ffmpeg"

    def slice_local_file(
        self,
        input_file: Path | str,
        output_file: Path | str,
        start_s: float,
        end_s: float,
        max_duration: float = 6.0,
        target_height: int = 480,
        crf: int = 28,
        timeout_seconds: float = 30.0,
    ) -> Path:
        """Slices and compresses a segment from a local video file using ffmpeg.
        
        Optimizations:
        - Fast seeking with -ss before -i
        - Stripped audio (-an)
        - H.264 constrained baseline/main profile with yuv420p
        - +faststart flag for instant stream initialization
        """
        if not is_ffmpeg_available(self.ffmpeg_bin):
            raise RuntimeError(f"FFmpeg binary '{self.ffmpeg_bin}' was not found in system PATH.")

        in_path = Path(input_file).resolve()
        if not in_path.exists():
            raise FileNotFoundError(f"Source video file not found: {in_path}")

        out_path = Path(output_file).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Sanitize duration
        if end_s <= start_s:
            end_s = start_s + max_duration
        duration = min(end_s - start_s, max_duration)
        effective_end = start_s + duration

        # Build optimized ffmpeg command
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-ss", str(round(start_s, 2)),
            "-to", str(round(effective_end, 2)),
            "-i", str(in_path),
            "-an",
            "-vf", f"scale=-2:{target_height}",
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_path),
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg slicing failed (code {result.returncode}): {result.stderr[-400:]}")

        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg produced an empty or missing output file at {out_path}")

        return out_path

    def slice_youtube_video(
        self,
        url_or_video_id: str,
        output_file: Path | str,
        start_s: float,
        end_s: float,
        max_duration: float = 6.0,
        target_height: int = 480,
        crf: int = 28,
        timeout_seconds: float = 60.0,
    ) -> Path:
        """Downloads a specific time slice from YouTube using yt-dlp and standardizes it with ffmpeg."""
        if not is_ytdlp_available():
            raise RuntimeError("yt-dlp is not installed. Install it via 'uv pip install yt-dlp'.")
        if not is_ffmpeg_available(self.ffmpeg_bin):
            raise RuntimeError("ffmpeg is required for slicing video sections.")

        import yt_dlp
        from yt_dlp.utils import download_range_func

        # Sanitize duration
        if end_s <= start_s:
            end_s = start_s + max_duration
        duration = min(end_s - start_s, max_duration)
        effective_end = start_s + duration

        # Normalize YouTube URL
        if not url_or_video_id.startswith("http://") and not url_or_video_id.startswith("https://"):
            video_url = f"https://www.youtube.com/watch?v={url_or_video_id}"
        else:
            video_url = url_or_video_id

        out_path = Path(output_file).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_download_template = str(Path(tmp_dir) / "raw_slice.%(ext)s")
            
            ydl_opts = {
                "format": "bestvideo[height<=720][ext=mp4]/bestvideo[height<=720]/best[height<=720]/best",
                "download_ranges": download_range_func(None, [(start_s, effective_end)]),
                "force_keyframes_at_cuts": True,
                "outtmpl": tmp_download_template,
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info))

            if not downloaded_file.exists():
                # Search for any downloaded file in tmp_dir
                candidates = list(Path(tmp_dir).glob("raw_slice.*"))
                if not candidates:
                    raise RuntimeError("yt-dlp failed to download section slice.")
                downloaded_file = candidates[0]

            # Transcode with standard ffmpeg pass to guarantee 480p, -an, yuv420p, +faststart
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-i", str(downloaded_file),
                "-an",
                "-vf", f"scale=-2:{target_height}",
                "-c:v", "libx264",
                "-crf", str(crf),
                "-preset", "veryfast",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(out_path),
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
            )

            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg transcode failed: {result.stderr[-400:]}")

        return out_path

    def create_chunk_clip(
        self,
        game_id: str,
        encounter_id: str,
        chunk_id: int,
        source_type: str,
        source_ref: str,
        start_s: float,
        end_s: float,
        max_duration: float = 6.0,
    ) -> Optional[ClipMetadata]:
        """Creates and stores a standardized micro-clip for a specific guide chunk.
        
        Returns ClipMetadata if successful, or None if the source does not support video slicing.
        """
        # Text-only sources have no video stream to slice
        if source_type in ("steam", "wiki") and not Path(source_ref).is_file():
            return None

        rel_path = get_relative_clip_path(game_id, encounter_id, chunk_id)
        target_abs = resolve_clip_path(rel_path, self.clips_dir.parent)

        # Idempotency / Caching: If clip already exists and is non-empty, reuse it directly
        if target_abs.exists() and target_abs.stat().st_size > 1024:
            return ClipMetadata(
                chunk_id=chunk_id,
                relative_path=rel_path,
                absolute_path=target_abs,
                start_s=start_s,
                end_s=end_s,
                duration_s=min(end_s - start_s, max_duration) if end_s > start_s else max_duration,
                file_size_bytes=target_abs.stat().st_size,
            )

        try:
            if source_type == "youtube":
                self.slice_youtube_video(
                    url_or_video_id=source_ref,
                    output_file=target_abs,
                    start_s=start_s,
                    end_s=end_s,
                    max_duration=max_duration,
                )
            elif Path(source_ref).is_file():
                self.slice_local_file(
                    input_file=Path(source_ref),
                    output_file=target_abs,
                    start_s=start_s,
                    end_s=end_s,
                    max_duration=max_duration,
                )
            else:
                return None

            return ClipMetadata(
                chunk_id=chunk_id,
                relative_path=rel_path,
                absolute_path=target_abs,
                start_s=start_s,
                end_s=end_s,
                duration_s=min(end_s - start_s, max_duration) if end_s > start_s else max_duration,
                file_size_bytes=target_abs.stat().st_size,
            )

        except Exception as err:
            # Slicing failure should log cleanly and degrade gracefully without breaking ingestion
            print(f"[VideoClipper Warning] Failed to generate clip for chunk {chunk_id}: {err}", file=sys.stderr)
            return None
