"""
Pipeline completo de geração de episódio:
article → enriquecimento (URL) → resumo → diálogo → TTS → áudio → vídeo → DB
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings
from database.db import get_session_factory
from database.models import Article, Episode
from ai.summarizer import summarize_article
from ai.dialogue_generator import generate_dialogue
from tts.voice_engine import generate_episode_audio
from tts.audio_mixer import mix_episode_audio, get_audio_duration

logger = logging.getLogger(__name__)


async def generate_episode_for_article(article_id: int) -> Optional[int]:
    """
    Pipeline completo: artigo → episódio em vídeo.
    Retorna episode_id em caso de sucesso, None em falha.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            logger.error(f"Artigo {article_id} não encontrado")
            return None

        # Verifica episódio já existente
        existing = db.query(Episode).filter(Episode.article_id == article_id).first()
        if existing and existing.video_path and Path(existing.video_path).exists():
            logger.info(f"Episódio já existe para artigo {article_id}")
            return existing.id

        logger.info(f"Gerando episódio para: {article.title[:60]}")

        # Captura valores antes de fechar a sessão
        art_title     = article.title
        art_content   = article.content or article.title
        art_source    = article.source
        art_category  = article.category or "geral"
        art_image_url = article.image_url
        art_summary   = article.summary
        art_url       = article.url

        # 1. Enriquecimento via URL (extrai entidades, sentimento, tópicos, etc.)
        enrichment = None
        try:
            from aggregator.enricher import enrich_url
            enrichment = enrich_url(art_url)
            if enrichment:
                logger.info(
                    f"Enriquecimento OK — sentimento={enrichment.get('sentimento')} "
                    f"impacto={enrichment.get('impacto')}"
                )
                # Se o enricher trouxe uma imagem melhor, usa ela
                if not art_image_url and enrichment.get("image_url"):
                    art_image_url = enrichment["image_url"]
                    article.image_url = art_image_url
                    db.commit()
        except Exception as e:
            logger.warning(f"Enriquecimento falhou (não crítico): {e}")

        # 2. Resumo
        if not art_summary:
            # Prefere o resumo do enriquecimento quando disponível
            if enrichment and enrichment.get("resumo"):
                art_summary = enrichment["resumo"]
            else:
                art_summary = summarize_article(art_title, art_content, art_source)
            article.summary = art_summary
            db.commit()

        # 3. Geração de diálogo com contexto enriquecido
        script = generate_dialogue(
            title=art_title,
            summary=art_summary or "",
            category=art_category,
            enrichment=enrichment,
        )

        # 4. Cria registro do episódio
        episode = Episode(
            article_id=article_id,
            script=json.dumps(script, ensure_ascii=False),
        )
        db.add(episode)
        db.commit()
        db.refresh(episode)
        episode_id = episode.id

    finally:
        db.close()

    # 5. Geração de áudio TTS
    audio_files = await generate_episode_audio(
        script, episode_id, category=art_category
    )
    if not audio_files:
        logger.error(f"Falha no TTS para episódio {episode_id}")
        return None

    # 6. Mix do áudio
    music_path = Path(__file__).parent / "assets" / "bg_music.mp3"
    final_audio = mix_episode_audio(
        audio_files, episode_id,
        music_path if music_path.exists() else None,
    )
    if not final_audio:
        logger.error(f"Falha no mix de áudio para episódio {episode_id}")
        return None

    # 7. Composição do vídeo (com efeitos animados + enrichment)
    from video.compositor import compose_video
    video_path = compose_video(
        episode_id=episode_id,
        article_title=art_title,
        article_image_url=art_image_url,
        script=script,
        audio_path=final_audio,
        category=art_category,
        enrichment=enrichment,
    )

    # 8. Atualiza DB com paths do episódio
    db = SessionLocal()
    try:
        ep = db.query(Episode).filter(Episode.id == episode_id).first()
        if ep:
            ep.audio_path = str(final_audio)
            ep.video_path = str(video_path) if video_path else None
            ep.duration_s = int(get_audio_duration(final_audio))
            db.commit()

        art = db.query(Article).filter(Article.id == article_id).first()
        if art:
            art.processed = True
            db.commit()
    finally:
        db.close()

    if video_path:
        logger.info(f"Episódio {episode_id} pronto: {video_path.name}")
    else:
        logger.warning(f"Composição de vídeo falhou — episódio apenas com áudio {episode_id}")

    return episode_id


async def process_top_articles(n: int = 3):
    """Gera episódios para os top N artigos não processados."""
    from aggregator.ranker import get_top_articles
    articles = get_top_articles(n=n)
    for article in articles:
        await generate_episode_for_article(article.id)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    article_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    result = asyncio.run(generate_episode_for_article(article_id))
    print(f"Episode ID: {result}" if result else "Falha ao gerar episódio")
