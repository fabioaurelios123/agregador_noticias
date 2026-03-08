"""
Streams video files to YouTube Live using FFmpeg RTMP.
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

YOUTUBE_RTMP_BASE = "rtmp://a.rtmp.youtube.com/live2"


def stream_video(video_path: Path, stream_key: Optional[str] = None, test_mode: bool = False) -> bool:
    """
    Stream a video file to YouTube Live via RTMP.
    test_mode: stream for 10 seconds only (for testing).
    """
    key = stream_key or settings.youtube_stream_key
    if not key and not test_mode:
        logger.error("YOUTUBE_STREAM_KEY not set")
        return False

    rtmp_url = f"{YOUTUBE_RTMP_BASE}/{key}" if key else "rtmp://localhost:1935/live/test"

    cmd = [
        "ffmpeg",
        "-re",                          # Read at native frame rate
        "-i", str(video_path),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "3000k",
        "-maxrate", "3000k",
        "-bufsize", "6000k",
        "-pix_fmt", "yuv420p",
        "-g", "60",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-f", "flv",
    ]

    if test_mode:
        cmd += ["-t", "10"]  # 10 seconds only

    cmd.append(rtmp_url)

    logger.info(f"Streaming {video_path.name} → {rtmp_url}")
    try:
        result = subprocess.run(cmd, timeout=3600)  # 1 hour max per video
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("Stream timed out")
        return False
    except Exception as e:
        logger.error(f"Stream error: {e}")
        return False


def stream_continuous(mode_fn=None):
    """
    Continuously stream videos. mode_fn() returns "live" or "replay".
    Blocks until stopped.
    """
    from stream.playlist_manager import get_next_episode
    import time

    logger.info("Starting continuous stream...")

    while True:
        mode = mode_fn() if mode_fn else "live"
        video = get_next_episode(mode=mode)

        if video and video.exists():
            logger.info(f"Streaming [{mode}]: {video.name}")
            stream_video(video)
        else:
            logger.info("No video available — waiting 30s...")
            time.sleep(30)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    test = "--test" in sys.argv
    video_arg = next((a for a in sys.argv[1:] if not a.startswith("--")), None)

    if video_arg:
        p = Path(video_arg)
        if p.exists():
            stream_video(p, test_mode=test)
        else:
            print(f"File not found: {p}")
    else:
        print("Usage: python -m stream.streamer [video.mp4] [--test]")
