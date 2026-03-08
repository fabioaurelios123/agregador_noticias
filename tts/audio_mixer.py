"""
Concatenates speech audio files and optionally adds a background music track.
Uses ffmpeg via subprocess.
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# Silence gap between speech lines (milliseconds)
PAUSE_MS = 600


def _build_ffmpeg_concat(audio_files: list[Path], output_path: Path) -> bool:
    """Concatenate audio files using ffmpeg concat demuxer."""
    # Filter out missing or empty files
    valid_files = [p for p in audio_files if p.exists() and p.stat().st_size >= 100]
    if not valid_files:
        logger.error("No valid audio files to concatenate (all empty or missing)")
        return False
    if len(valid_files) < len(audio_files):
        logger.warning(f"Skipping {len(audio_files) - len(valid_files)} empty/missing audio files")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in valid_files:
            f.write(f"file '{p.absolute()}'\n")
        f.write(f"duration 0\n")  # ensure last file plays fully
        list_path = f.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c:a", "libmp3lame",
            "-q:a", "4",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffmpeg concat error:\n{result.stderr}")
            return False
        return True
    finally:
        Path(list_path).unlink(missing_ok=True)


def _add_background_music(
    speech_path: Path,
    music_path: Path,
    output_path: Path,
    music_volume: float = 0.15,
) -> bool:
    """Mix speech with background music at reduced volume."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(speech_path),
            "-stream_loop", "-1",
            "-i", str(music_path),
            "-filter_complex",
            f"[1:a]volume={music_volume}[bg];[0:a][bg]amix=inputs=2:duration=first[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-q:a", "4",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffmpeg mix error:\n{result.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Audio mix failed: {e}")
        return False


def mix_episode_audio(
    audio_files: list[Path],
    episode_id: int,
    music_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Mix individual speech files into a single episode audio file.
    Returns path to final mixed .mp3, or None on failure.
    """
    output_dir = settings.video_output_path / f"episode_{episode_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    concat_path = output_dir / "speech_concat.mp3"
    final_path = output_dir / "audio_final.mp3"

    if not _build_ffmpeg_concat(audio_files, concat_path):
        return None

    if music_path and music_path.exists():
        if not _add_background_music(concat_path, music_path, final_path):
            # Fall back to just speech
            concat_path.rename(final_path)
    else:
        concat_path.rename(final_path)

    logger.info(f"Mixed audio saved: {final_path}")
    return final_path


def get_audio_duration(audio_path: Path) -> float:
    """Return duration of audio file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0
