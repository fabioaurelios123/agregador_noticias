"""
Generates speech audio files for each persona.
Primary engine: edge-tts (high quality, Neural voices).
Fallback engine: gTTS (Google TTS) — works on cloud VMs where edge-tts gets 403.
Persona differentiation on gTTS fallback is done via ffmpeg pitch/tempo filters.
"""
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Engine availability ────────────────────────────────────────────────────────

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts not installed")

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    logger.warning("gtts not installed — install with: pip install gtts")

# ── Persona configs ────────────────────────────────────────────────────────────

# edge-tts: voice + SSML rate/pitch adjustments
VOICES_EDGE = {
    "ana": {
        "voice": "pt-BR-FranciscaNeural",
        "rate":  "+0%",
        "pitch": "+0Hz",
    },
    "carlos": {
        "voice": "pt-BR-AntonioNeural",
        "rate":  "-5%",
        "pitch": "-3Hz",
    },
    "guest": {
        "politica": {"voice": "pt-BR-FranciscaNeural", "rate": "+5%",  "pitch": "+8Hz"},
        "economia": {"voice": "pt-BR-AntonioNeural",   "rate": "+0%",  "pitch": "+5Hz"},
        "saude":    {"voice": "pt-BR-AntonioNeural",   "rate": "-3%",  "pitch": "+8Hz"},
        "tech":     {"voice": "pt-BR-FranciscaNeural", "rate": "+8%",  "pitch": "+5Hz"},
        "esporte":  {"voice": "pt-BR-AntonioNeural",   "rate": "+10%", "pitch": "+3Hz"},
        "geral":    {"voice": "pt-BR-AntonioNeural",   "rate": "+0%",  "pitch": "+5Hz"},
    },
}

# gTTS fallback: ffmpeg atempo + asetrate filters to differentiate personas
# atempo: 0.85–1.15 (speed), pitch_semitones: +/- semitones via asetrate trick
VOICES_GTTS = {
    "ana":    {"speed": 1.00, "pitch": 0},    # voz feminina normal
    "carlos": {"speed": 0.92, "pitch": -2},   # um pouco mais grave e lento
    "guest": {
        "politica": {"speed": 1.05, "pitch": +1},
        "economia": {"speed": 0.95, "pitch": -1},
        "saude":    {"speed": 0.93, "pitch": +2},
        "tech":     {"speed": 1.08, "pitch": +1},
        "esporte":  {"speed": 1.10, "pitch": 0},
        "geral":    {"speed": 1.00, "pitch": 0},
    },
}


def _get_voice_config(persona: str, category: str = "geral") -> dict:
    if persona == "guest":
        return VOICES_EDGE["guest"].get(category, VOICES_EDGE["guest"]["geral"])
    return VOICES_EDGE.get(persona, VOICES_EDGE["ana"])


def _get_gtts_config(persona: str, category: str = "geral") -> dict:
    if persona == "guest":
        return VOICES_GTTS["guest"].get(category, VOICES_GTTS["guest"]["geral"])
    return VOICES_GTTS.get(persona, VOICES_GTTS["ana"])


# ── edge-tts engine ────────────────────────────────────────────────────────────

async def _generate_edge(text: str, voice: str, rate: str, pitch: str, output_path: Path) -> bool:
    """Generate speech with edge-tts. Returns False on any error (including 403)."""
    if not EDGE_TTS_AVAILABLE:
        return False
    try:
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(str(output_path))
        if not output_path.exists() or output_path.stat().st_size < 100:
            logger.debug(f"edge-tts produced empty file for voice={voice} (likely 403)")
            output_path.unlink(missing_ok=True)
            return False
        return True
    except Exception as e:
        logger.debug(f"edge-tts failed for voice={voice}: {e}")
        output_path.unlink(missing_ok=True)
        return False


# ── gTTS fallback engine ───────────────────────────────────────────────────────

def _apply_ffmpeg_voice(input_mp3: Path, output_mp3: Path, speed: float, pitch: int) -> bool:
    """
    Apply speed and pitch adjustments via ffmpeg.
    pitch in semitones: uses asetrate + atempo trick.
    """
    try:
        # Build filter chain
        filters = []
        if pitch != 0:
            # Shift pitch: change sample rate → resample back to 44100
            semitone_factor = 2 ** (pitch / 12)
            new_rate = int(44100 * semitone_factor)
            filters.append(f"asetrate={new_rate}")
            filters.append("aresample=44100")

        if abs(speed - 1.0) > 0.01:
            # atempo only works in 0.5–2.0 range
            s = max(0.5, min(2.0, speed))
            filters.append(f"atempo={s:.2f}")

        filter_str = ",".join(filters) if filters else "anull"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_mp3),
            "-af", filter_str,
            "-c:a", "libmp3lame", "-q:a", "4",
            str(output_mp3),
        ]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0 and output_mp3.exists() and output_mp3.stat().st_size > 100
    except Exception as e:
        logger.warning(f"ffmpeg voice filter failed: {e}")
        return False


def _generate_gtts(text: str, persona: str, category: str, output_path: Path) -> bool:
    """Generate speech with gTTS + ffmpeg persona filters."""
    if not GTTS_AVAILABLE:
        logger.error("gTTS not available. Install with: pip install gtts")
        return False

    # Limpa marcações que não devem ser lidas
    import re
    clean_text = re.sub(r'<[^>]+>', '', text).strip()
    if not clean_text:
        return False

    cfg = _get_gtts_config(persona, category)

    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        tts = gTTS(text=clean_text, lang="pt", tld="com.br", slow=False)
        tts.save(str(tmp_path))

        if not tmp_path.exists() or tmp_path.stat().st_size < 100:
            logger.error("gTTS produced empty file")
            tmp_path.unlink(missing_ok=True)
            return False

        speed = cfg.get("speed", 1.0)
        pitch = cfg.get("pitch", 0)

        # Se não há ajustes, só renomeia
        if abs(speed - 1.0) < 0.01 and pitch == 0:
            tmp_path.rename(output_path)
            return True

        ok = _apply_ffmpeg_voice(tmp_path, output_path, speed, pitch)
        tmp_path.unlink(missing_ok=True)

        if not ok:
            # Fallback: usa sem filtros
            tts2 = gTTS(text=clean_text, lang="pt", tld="com.br", slow=False)
            tts2.save(str(output_path))
            return output_path.exists() and output_path.stat().st_size > 100

        return ok
    except Exception as e:
        logger.error(f"gTTS failed for persona={persona}: {e}")
        output_path.unlink(missing_ok=True)
        return False


# ── Unified speech generator ───────────────────────────────────────────────────

async def _generate_speech(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    output_path: Path,
    persona: str = "ana",
    category: str = "geral",
) -> bool:
    """
    Try edge-tts first. If it fails (403 on cloud VMs), fallback to gTTS.
    """
    # 1. edge-tts
    if EDGE_TTS_AVAILABLE:
        ok = await _generate_edge(text, voice, rate, pitch, output_path)
        if ok:
            return True
        logger.warning(f"edge-tts failed for {persona} — trying gTTS fallback")

    # 2. gTTS fallback
    if GTTS_AVAILABLE:
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(
            None, _generate_gtts, text, persona, category, output_path
        )
        if ok:
            logger.debug(f"gTTS fallback OK for persona={persona}")
            return True

    logger.error(f"All TTS engines failed for persona={persona}: {text[:60]}")
    return False


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_speech_sync(
    text: str,
    persona: str,
    output_path: Path,
    category: str = "geral",
) -> bool:
    """Synchronous wrapper."""
    cfg = _get_voice_config(persona, category)
    return asyncio.run(_generate_speech(
        text, cfg["voice"], cfg["rate"], cfg["pitch"],
        output_path, persona, category,
    ))


async def generate_episode_audio(
    script: list[dict],
    episode_id: int,
    category: str = "geral",
) -> Optional[list[Path]]:
    """
    Generate individual audio files for each script line.
    Returns list of .mp3 paths, or None on total failure.
    """
    output_dir = settings.video_output_path / f"episode_{episode_id}" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = []

    for i, line in enumerate(script):
        persona = line.get("persona", "ana")
        text    = line.get("text", "").strip()
        if not text:
            continue

        # Filtra textos claramente inválidos (HTML, URLs, etc.)
        import re
        if re.match(r'^<|^https?://', text):
            logger.warning(f"Skipping invalid TTS text: {text[:60]}")
            continue

        cfg  = _get_voice_config(persona, category)
        path = output_dir / f"line_{i:03d}_{persona}.mp3"

        ok = await _generate_speech(
            text, cfg["voice"], cfg["rate"], cfg["pitch"],
            path, persona, category,
        )
        if ok:
            audio_files.append(path)
            logger.debug(f"Generated audio: {path.name}")
        else:
            logger.warning(f"Failed to generate audio for: {text[:50]}")

    return audio_files if audio_files else None


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)
    text = sys.argv[1] if len(sys.argv) > 1 else "Boa tarde, eu sou Ana Silva do Brasil24."
    persona = sys.argv[2] if len(sys.argv) > 2 else "ana"
    out = Path(f"test_{persona}.mp3")
    ok = generate_speech_sync(text, persona, out)
    print(f"Generated: {out}" if ok else "Failed to generate speech")
