"""
Generates speech audio files using edge-tts for each persona.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts not installed")

# Persona voice configs
VOICES = {
    "ana": {
        "voice": "pt-BR-FranciscaNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
    },
    "carlos": {
        "voice": "pt-BR-AntonioNeural",
        "rate": "-5%",
        "pitch": "-3Hz",
    },
    "guest": {
        "politica": {"voice": "pt-BR-FranciscaNeural", "rate": "+5%", "pitch": "+8Hz"},
        "economia": {"voice": "pt-BR-AntonioNeural", "rate": "+0%", "pitch": "+5Hz"},
        "saude":    {"voice": "pt-BR-AntonioNeural", "rate": "-3%", "pitch": "+8Hz"},
        "tech":     {"voice": "pt-BR-FranciscaNeural", "rate": "+8%", "pitch": "+5Hz"},
        "esporte":  {"voice": "pt-BR-AntonioNeural", "rate": "+10%", "pitch": "+3Hz"},
        "geral":    {"voice": "pt-BR-AntonioNeural", "rate": "+0%", "pitch": "+5Hz"},
    },
}


def _get_voice_config(persona: str, category: str = "geral") -> dict:
    if persona == "guest":
        return VOICES["guest"].get(category, VOICES["guest"]["geral"])
    return VOICES.get(persona, VOICES["ana"])


async def _generate_speech(text: str, voice: str, rate: str, pitch: str, output_path: Path) -> bool:
    """Generate a single speech file using edge-tts."""
    if not EDGE_TTS_AVAILABLE:
        logger.error("edge-tts not available")
        return False
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))
        # Validate file was actually written (403/network errors create empty files)
        if not output_path.exists() or output_path.stat().st_size < 100:
            logger.error(f"edge-tts produced empty/invalid file for voice={voice}")
            output_path.unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        logger.error(f"edge-tts error for voice={voice}: {e}")
        output_path.unlink(missing_ok=True)
        return False


def generate_speech_sync(
    text: str,
    persona: str,
    output_path: Path,
    category: str = "geral",
) -> bool:
    """Synchronous wrapper for generating a single speech file."""
    cfg = _get_voice_config(persona, category)
    return asyncio.run(_generate_speech(text, cfg["voice"], cfg["rate"], cfg["pitch"], output_path))


async def generate_episode_audio(
    script: list[dict],
    episode_id: int,
    category: str = "geral",
) -> Optional[list[Path]]:
    """
    Generate individual audio files for each line in the script.
    Returns list of paths to generated .mp3 files, or None on failure.
    """
    output_dir = settings.video_output_path / f"episode_{episode_id}" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = []
    tasks = []

    for i, line in enumerate(script):
        persona = line.get("persona", "ana")
        text = line.get("text", "").strip()
        if not text:
            continue

        cfg = _get_voice_config(persona, category)
        path = output_dir / f"line_{i:03d}_{persona}.mp3"
        tasks.append((path, text, cfg["voice"], cfg["rate"], cfg["pitch"]))

    for path, text, voice, rate, pitch in tasks:
        ok = await _generate_speech(text, voice, rate, pitch, path)
        if ok:
            audio_files.append(path)
            logger.debug(f"Generated audio: {path.name}")
        else:
            logger.warning(f"Failed to generate audio for: {text[:50]}")

    return audio_files if audio_files else None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    text = sys.argv[1] if len(sys.argv) > 1 else "Boa tarde, eu sou Ana Silva do Brasil24."
    out = Path("test_speech.mp3")
    ok = generate_speech_sync(text, "ana", out)
    print(f"Generated: {out}" if ok else "Failed to generate speech")
