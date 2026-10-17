"""Unit tests for the Ahead-of-Time VideoClipper engine."""

import os
import subprocess
from pathlib import Path
import pytest

from core.ingestion.clipper import (
    VideoClipper,
    get_clips_dir,
    get_relative_clip_path,
    is_ffmpeg_available,
    resolve_clip_path,
)


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    """Generates a lightweight 3-second synthetic test MP4 video using ffmpeg."""
    if not is_ffmpeg_available():
        pytest.skip("ffmpeg is not installed on this system")

    video_path = tmp_path / "synthetic_gameplay.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=3:size=640x360:rate=30",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(video_path),
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return video_path


def test_path_helpers(tmp_path: Path):
    """Verifies relative and absolute clip path generation."""
    rel = get_relative_clip_path("sekiro", "genichiro", 10)
    assert rel == "clips/sekiro/genichiro_10.mp4"

    # Sanitization of special characters in game / encounter names
    rel_dirty = get_relative_clip_path("Elden Ring!", "Malenia, Blade of Miquella", 5)
    assert rel_dirty == "clips/elden_ring_/malenia__blade_of_miquella_5.mp4"

    # Path resolution
    resolved = resolve_clip_path(rel, base_dir=tmp_path)
    assert resolved == tmp_path / "clips/sekiro/genichiro_10.mp4"


def test_ffmpeg_availability():
    """Verifies ffmpeg presence detection."""
    assert is_ffmpeg_available() is True
    assert is_ffmpeg_available("invalid_binary_name_never_exists") is False


def test_slice_local_video(synthetic_video: Path, tmp_path: Path):
    """Tests slicing, re-encoding, and compression of a local video file."""
    output_clip = tmp_path / "output_clip.mp4"
    clipper = VideoClipper(clips_dir=tmp_path)

    result_path = clipper.slice_local_file(
        input_file=synthetic_video,
        output_file=output_clip,
        start_s=0.5,
        end_s=2.5,
        max_duration=3.0,
        target_height=480,
    )

    assert result_path.exists()
    assert result_path.stat().st_size > 1024  # Valid non-empty media file

    # Verify duration cap enforcement
    capped_clip = tmp_path / "capped_clip.mp4"
    res_capped = clipper.slice_local_file(
        input_file=synthetic_video,
        output_file=capped_clip,
        start_s=0.0,
        end_s=10.0,  # Deliberately exceeds max_duration
        max_duration=2.0,
    )
    assert res_capped.exists()


def test_create_chunk_clip_caching_and_lifecycle(synthetic_video: Path, tmp_path: Path):
    """Tests create_chunk_clip lifecycle, metadata return, and disk caching."""
    clips_dir = tmp_path / "clips"
    clipper = VideoClipper(clips_dir=clips_dir)

    # 1. Text source should return None (no video stream)
    wiki_res = clipper.create_chunk_clip(
        game_id="sekiro",
        encounter_id="genichiro",
        chunk_id=1,
        source_type="wiki",
        source_ref="https://sekiro.fandom.com/wiki/Genichiro",
        start_s=0.0,
        end_s=0.0,
    )
    assert wiki_res is None

    # 2. Local video source creates clip metadata
    clip_meta = clipper.create_chunk_clip(
        game_id="sekiro",
        encounter_id="genichiro",
        chunk_id=42,
        source_type="local",
        source_ref=str(synthetic_video),
        start_s=1.0,
        end_s=2.5,
        max_duration=4.0,
    )
    assert clip_meta is not None
    assert clip_meta.chunk_id == 42
    assert clip_meta.format == "mp4"
    assert clip_meta.absolute_path.exists()
    assert clip_meta.file_size_bytes > 1024

    # 3. Subsequent call should hit cache and reuse existing file
    cached_meta = clipper.create_chunk_clip(
        game_id="sekiro",
        encounter_id="genichiro",
        chunk_id=42,
        source_type="local",
        source_ref=str(synthetic_video),
        start_s=1.0,
        end_s=2.5,
    )
    assert cached_meta is not None
    assert cached_meta.absolute_path == clip_meta.absolute_path
    assert cached_meta.file_size_bytes == clip_meta.file_size_bytes


def test_slice_local_file_missing_source(tmp_path: Path):
    """Verifies graceful FileNotFoundError on invalid input."""
    clipper = VideoClipper(clips_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        clipper.slice_local_file(
            input_file=tmp_path / "non_existent.mp4",
            output_file=tmp_path / "out.mp4",
            start_s=0.0,
            end_s=2.0,
        )
