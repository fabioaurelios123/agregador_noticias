"""
Monta o vídeo final do episódio usando MoviePy.
- Com imagem real: Ken Burns (zoom lento) + overlays animados
- Sem imagem: fundo genérico animado com gradiente + efeitos
- Overlay de entidades rotativo, ticker animado, badge AO VIVO piscando
"""
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from config.settings import settings
from tts.audio_mixer import get_audio_duration

logger = logging.getLogger(__name__)

try:
    from moviepy.editor import AudioFileClip, VideoClip, concatenate_videoclips
    from PIL import Image
    import httpx
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    logger.warning("moviepy/Pillow não instalado — geração de vídeo desativada")


def _download_image(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=12, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            # Verifica se é realmente uma imagem
            ct = r.headers.get("content-type", "")
            if "image" not in ct and not any(url.lower().endswith(e) for e in [".jpg", ".jpeg", ".png", ".webp"]):
                logger.warning(f"URL não parece ser imagem (content-type: {ct})")
                return False
            dest.write_bytes(r.content)
            return True
    except Exception as e:
        logger.warning(f"Falha ao baixar imagem {url}: {e}")
        return False


def compose_video(
    episode_id: int,
    article_title: str,
    article_image_url: Optional[str],
    script: list[dict],
    audio_path: Path,
    category: str = "geral",
    enrichment: Optional[dict] = None,
) -> Optional[Path]:
    """
    Monta o vídeo final do episódio.
    Retorna o path do .mp4 ou None em caso de falha.
    """
    if not MOVIEPY_AVAILABLE:
        logger.error("MoviePy não disponível")
        return None

    from video.news_effects import (
        make_generic_bg,
        apply_ken_burns,
        prepare_image_bg,
        draw_frame_overlays,
        build_entity_list,
    )

    output_dir = settings.video_output_path / f"episode_{episode_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "video_final.mp4"

    # ── Baixar imagem da notícia ───────────────────────────────────────────
    img_path = output_dir / "article_image.jpg"
    has_image = False
    image_bg_array = None

    if article_image_url:
        has_image = _download_image(article_image_url, img_path)

    if has_image:
        image_bg_array = prepare_image_bg(img_path)
        if image_bg_array is None:
            has_image = False

    # Dados do enriquecimento
    sentiment = "neutro"
    if enrichment:
        sentiment = enrichment.get("sentimento", "neutro")

    entities = build_entity_list(enrichment)
    ticker_text = article_title[:120]

    # ── Duração total do áudio ─────────────────────────────────────────────
    total_duration = get_audio_duration(audio_path)
    if total_duration <= 0:
        logger.error("Não foi possível determinar a duração do áudio")
        return None

    # ── Calcular duração por segmento ─────────────────────────────────────
    n_segs = max(len(script), 1)
    seg_duration = total_duration / n_segs

    # Pré-calcula os start times de cada segmento
    seg_starts = [i * seg_duration for i in range(n_segs)]

    # ── make_frame: gera cada frame com base no tempo global t ────────────
    def make_frame(t: float) -> np.ndarray:
        # Descobre em qual segmento estamos
        seg_idx = min(int(t / seg_duration), n_segs - 1)
        seg_start = seg_starts[seg_idx]
        line = script[seg_idx] if seg_idx < len(script) else script[-1]
        persona = line.get("persona", "ana")

        # Fundo
        if has_image:
            bg = apply_ken_burns(image_bg_array, t, total_duration)
        else:
            bg = make_generic_bg(t, category, sentiment)

        # Overlays
        frame = draw_frame_overlays(
            bg=bg,
            t=t,
            seg_start=seg_start,
            title=article_title,
            persona=persona,
            entities=entities,
            sentiment=sentiment,
            category=category,
            ticker_text=ticker_text,
            seg_index=seg_idx,
            total_segs=n_segs,
        )
        return frame

    # ── Criar VideoClip animado ────────────────────────────────────────────
    video_clip = VideoClip(make_frame, duration=total_duration)
    audio_clip = AudioFileClip(str(audio_path))
    final = video_clip.set_audio(audio_clip)

    try:
        final.write_videofile(
            str(output_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            preset="veryfast",
            temp_audiofile=str(output_dir / "temp_audio.aac"),
            remove_temp=True,
            logger=None,
        )
        logger.info(f"Vídeo composto: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Falha na composição do vídeo: {e}", exc_info=True)
        return None
    finally:
        final.close()
        audio_clip.close()
