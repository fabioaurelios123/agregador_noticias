"""
Pipeline de leitura simples:
  artigo → texto limpo → TTS → áudio final

Sem IA. Sem diálogos. Sem enriquecimento.
Lê o conteúdo completo do artigo com uma única voz neutra.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings
from database.db import get_session_factory
from database.models import Article, Episode
from reader.text_cleaner import build_reading_text, split_into_chunks
from tts.audio_mixer import get_audio_duration, mix_episode_audio

logger = logging.getLogger(__name__)

# Voz padrão para leitura simples (neutra, clara)
READER_VOICE = "pt-BR-FranciscaNeural"
READER_RATE = "+0%"
READER_PITCH = "+0Hz"
READER_PERSONA = "ana"


async def _tts_chunk(text: str, output_path: Path, category: str = "geral") -> bool:
    """Gera áudio para um chunk de texto via TTS (sem IA)."""
    from tts.voice_engine import _generate_speech
    return await _generate_speech(
        text=text,
        voice=READER_VOICE,
        rate=READER_RATE,
        pitch=READER_PITCH,
        output_path=output_path,
        persona=READER_PERSONA,
        category=category,
    )


async def generate_simple_audio(
    article_id: int,
    with_music: bool = False,
) -> Optional[Path]:
    """
    Gera áudio simples para um artigo — lê o conteúdo completo sem IA.

    Retorna o caminho do arquivo .mp3 final, ou None em caso de falha.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()

    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            logger.error(f"Artigo {article_id} não encontrado")
            return None

        art_title = article.title
        art_content = article.content or ""
        art_source = article.source or "Brasil24"
        art_category = article.category or "geral"
        art_id = article.id

    finally:
        db.close()

    # Monta o texto de leitura — título + conteúdo completo, sem IA
    full_text = build_reading_text(art_title, art_content, art_source)
    chunks = split_into_chunks(full_text)

    logger.info(
        f"Leitura simples | artigo={art_id} | chunks={len(chunks)} | "
        f"chars_total={len(full_text)}"
    )

    # Diretório de saída isolado por artigo
    output_dir = settings.video_output_path / f"simple_{art_id}" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Gera um arquivo de áudio por chunk
    audio_files: list[Path] = []
    for i, chunk in enumerate(chunks):
        chunk_path = output_dir / f"chunk_{i:03d}.mp3"
        ok = await _tts_chunk(chunk, chunk_path, art_category)
        if ok:
            audio_files.append(chunk_path)
            logger.debug(f"  chunk {i:03d} gerado: {len(chunk)} chars")
        else:
            logger.warning(f"  chunk {i:03d} falhou — pulando")

    if not audio_files:
        logger.error(f"Nenhum áudio gerado para artigo {art_id}")
        return None

    # Mix: concatena todos os chunks em um único MP3
    # Usa episode_id negativo para não colidir com episódios normais
    music_path = None
    if with_music:
        music_path = Path(__file__).parent.parent / "video" / "assets" / "bg_music.mp3"
        if not music_path.exists():
            music_path = None

    final_audio = _mix_simple_audio(audio_files, art_id, music_path)
    if not final_audio:
        logger.error(f"Falha no mix de áudio para artigo {art_id}")
        return None

    duration = get_audio_duration(final_audio)
    logger.info(
        f"Áudio simples pronto | artigo={art_id} | "
        f"duração={duration:.1f}s | {final_audio}"
    )
    return final_audio


def _mix_simple_audio(
    audio_files: list[Path],
    article_id: int,
    music_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Concatena os chunks de áudio. Reutiliza o mix_episode_audio existente,
    mas gravando em diretório próprio do leitor simples.
    """
    import subprocess
    import tempfile

    output_dir = settings.video_output_path / f"simple_{article_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    final_path = output_dir / "leitura_completa.mp3"
    concat_path = output_dir / "concat_tmp.mp3"

    # Filtra arquivos válidos
    valid = [p for p in audio_files if p.exists() and p.stat().st_size >= 100]
    if not valid:
        return None

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in valid:
            f.write(f"file '{p.absolute()}'\n")
        f.write("duration 0\n")
        list_path = f.name

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:a", "libmp3lame", "-q:a", "4",
            str(concat_path),
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            logger.error("ffmpeg concat falhou no leitor simples")
            return None
    finally:
        Path(list_path).unlink(missing_ok=True)

    if music_path and music_path.exists():
        cmd_mix = [
            "ffmpeg", "-y",
            "-i", str(concat_path),
            "-stream_loop", "-1",
            "-i", str(music_path),
            "-filter_complex",
            "[1:a]volume=0.10[bg];[0:a][bg]amix=inputs=2:duration=first[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "4",
            str(final_path),
        ]
        result = subprocess.run(cmd_mix, capture_output=True)
        if result.returncode == 0:
            concat_path.unlink(missing_ok=True)
        else:
            concat_path.rename(final_path)
    else:
        concat_path.rename(final_path)

    return final_path if final_path.exists() else None


async def process_top_articles_simple(
    n: int = 5,
    with_music: bool = False,
) -> list[dict]:
    """
    Gera áudio de leitura simples para os top N artigos não processados.
    Retorna lista de resultados com article_id, título e caminho do áudio.
    """
    from aggregator.ranker import get_top_articles

    articles = get_top_articles(n=n)
    results = []

    for article in articles:
        logger.info(f"Processando artigo simples: {article.title[:60]}")
        audio_path = await generate_simple_audio(article.id, with_music=with_music)
        results.append({
            "article_id": article.id,
            "title": article.title,
            "source": article.source,
            "category": article.category,
            "audio_path": str(audio_path) if audio_path else None,
            "success": audio_path is not None,
        })

    return results
