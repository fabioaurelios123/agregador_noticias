"""
Concatena episódios com vinhetas usando ffmpeg -c copy (sem re-encoding).
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_master_video(
    episode_paths: list[Path],
    output_path: Path,
    vignette_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Concatena vinheta + ep1 + vinheta + ep2 + ... em um único MP4.
    Usa ffmpeg -c copy para ser rápido (sem re-encoding).
    Retorna output_path em sucesso, None em falha.
    """
    if not episode_paths:
        logger.error("Nenhum episódio para concatenar")
        return None

    # Filtra arquivos que existem
    valid = [p for p in episode_paths if p.exists()]
    if not valid:
        logger.error("Nenhum arquivo de episódio encontrado no disco")
        return None

    if len(valid) < len(episode_paths):
        logger.warning(f"  {len(episode_paths) - len(valid)} episódio(s) ausentes — continuando com {len(valid)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        list_path = Path(f.name)
        # Vinheta de abertura
        if vignette_path and vignette_path.exists():
            f.write(f"file '{vignette_path.absolute()}'\n")
        # Episódios com vinheta entre eles
        for i, ep in enumerate(valid):
            f.write(f"file '{ep.absolute()}'\n")
            if i < len(valid) - 1 and vignette_path and vignette_path.exists():
                f.write(f"file '{vignette_path.absolute()}'\n")

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffmpeg concat falhou:\n{result.stderr[-800:]}")
            return None

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(f"Master video: {output_path} ({size_mb:.1f}MB, {len(valid)} episódios)")
        return output_path

    except Exception as e:
        logger.error(f"Erro na concatenação: {e}")
        return None
    finally:
        list_path.unlink(missing_ok=True)


def get_total_duration(video_paths: list[Path]) -> float:
    """Retorna duração total em segundos de uma lista de vídeos."""
    total = 0.0
    for p in video_paths:
        if not p.exists():
            continue
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(p)],
                capture_output=True, text=True,
            )
            total += float(result.stdout.strip() or 0)
        except Exception:
            pass
    return total
