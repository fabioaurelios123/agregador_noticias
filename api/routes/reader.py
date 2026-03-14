"""
API routes para o Leitor Simples de Notícias.
Sem IA — apenas leitura direta do artigo em áudio.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reader", tags=["leitor-simples"])


class SimpleReaderRequest(BaseModel):
    top_n: int = 5
    with_music: bool = False


class SimpleReaderResult(BaseModel):
    article_id: int
    title: str
    source: str | None
    category: str | None
    audio_path: str | None
    success: bool


@router.post("/generate", response_model=list[SimpleReaderResult])
async def generate_simple_readings(request: SimpleReaderRequest):
    """
    Gera áudio de leitura simples para os top N artigos mais importantes.
    Sem IA — lê o conteúdo completo do artigo diretamente.
    """
    from reader.reader_pipeline import process_top_articles_simple

    results = await process_top_articles_simple(
        n=request.top_n,
        with_music=request.with_music,
    )
    return [SimpleReaderResult(**r) for r in results]


@router.post("/generate/{article_id}", response_model=SimpleReaderResult)
async def generate_single_reading(article_id: int, with_music: bool = False):
    """
    Gera áudio de leitura simples para um artigo específico.
    """
    from reader.reader_pipeline import generate_simple_audio
    from database.db import get_session_factory
    from database.models import Article

    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(status_code=404, detail=f"Artigo {article_id} não encontrado")
        title = article.title
        source = article.source
        category = article.category
    finally:
        db.close()

    audio_path = await generate_simple_audio(article_id, with_music=with_music)
    return SimpleReaderResult(
        article_id=article_id,
        title=title,
        source=source,
        category=category,
        audio_path=str(audio_path) if audio_path else None,
        success=audio_path is not None,
    )


@router.get("/audio/{article_id}")
async def download_simple_audio(article_id: int):
    """
    Retorna o arquivo de áudio gerado para um artigo (modo simples).
    """
    from config.settings import settings

    audio_path = settings.video_output_path / f"simple_{article_id}" / "leitura_completa.mp3"
    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Áudio simples não encontrado para artigo {article_id}. Gere primeiro via POST /api/reader/generate/{article_id}"
        )
    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
        filename=f"noticia_{article_id}.mp3",
    )


@router.get("/status")
async def reader_status():
    """Retorna artigos com áudio simples já gerado."""
    from config.settings import settings

    output_dir = settings.video_output_path
    if not output_dir.exists():
        return {"audios": [], "total": 0}

    audios = []
    for path in sorted(output_dir.glob("simple_*/leitura_completa.mp3")):
        article_id = int(path.parent.name.replace("simple_", ""))
        audios.append({
            "article_id": article_id,
            "audio_path": str(path),
            "size_kb": round(path.stat().st_size / 1024, 1),
        })

    return {"audios": audios, "total": len(audios)}
