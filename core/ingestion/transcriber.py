"""Whisper audio fallback worker for videos with zero subtitles.

Uses faster-whisper with CTranslate2 and INT8 quantization on CPU
to preserve 100% of GPU VRAM for the active game.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional
import yt_dlp

# Allow direct execution
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ingestion.chunker import CaptionCue


class WhisperTranscriber:
    """Fallback transcriber extracting audio and generating timestamped cues."""

    def __init__(
        self,
        model_size: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 4,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model = None

    @property
    def model(self):
        """Lazy loads the faster-whisper model only when needed."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "faster-whisper is not installed. Run 'uv pip install faster-whisper' to enable audio transcription fallback."
                ) from e

            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
            )
        return self._model

    def _download_audio(self, video_url: str, output_dir: Path) -> Path:
        """Downloads audio track only via yt-dlp to a temporary file."""
        output_template = str(output_dir / "%(id)s.%(ext)s")
        ydl_opts = {
            "format": "ba/b[ext=m4a]/ba*",  # Best audio stream only
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info)
            return Path(filename)

    def transcribe(self, video_url: str) -> List[CaptionCue]:
        """Downloads audio and returns timestamped CaptionCue objects."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            audio_file = self._download_audio(video_url, tmp_path)

            segments, _ = self.model.transcribe(
                str(audio_file),
                beam_size=1,  # Greedy search for maximum speed
                language="en",
                condition_on_previous_text=False,
            )

            cues: List[CaptionCue] = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    cues.append(
                        CaptionCue(
                            start_s=round(seg.start, 2),
                            end_s=round(seg.end, 2),
                            text=text,
                        )
                    )

            return cues
