"""
Pipeline em lote: fetch por fonte → dedup IA → gera episódios → concat master video → stream.
"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from config.settings import settings
from database.db import get_session_factory
from database.models import BatchRun, Episode

logger = logging.getLogger(__name__)

# Referência ao processo de stream ativo (gerenciado por api/routes/admin.py)
_stream_process = None


async def run_batch_pipeline(
    top_n_per_source: int = 5,
    min_videos_before_stream: int = 3,
    stream_after: bool = True,
    category_filter: Optional[str] = None,
    batch_run_id: Optional[int] = None,
    log_callback: Optional[Callable[[str], None]] = None,
) -> int:
    """
    Pipeline completo:
    1. Cria BatchRun no banco
    2. Fetch top N por fonte
    3. Agrupa por evento (dedup IA)
    4. Gera episódio para cada grupo único
    5. Se >= min_videos: concatena com vinheta → master MP4
    6. Se stream_after: inicia transmissão YouTube
    Retorna batch_run_id.
    """
    db = get_session_factory()()

    def log(msg: str):
        ts = datetime.utcnow().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        logger.info(msg)
        if log_callback:
            log_callback(line)
        # Persiste no banco
        try:
            br = db.query(BatchRun).filter(BatchRun.id == batch_run_id).first()
            if br:
                br.log = (br.log or "") + line + "\n"
                db.commit()
        except Exception:
            pass

    # ── 1. Cria ou reutiliza BatchRun ─────────────────────────────────────────
    if batch_run_id is None:
        br = BatchRun(
            status="running",
            category_filter=category_filter,
        )
        db.add(br)
        db.commit()
        db.refresh(br)
        batch_run_id = br.id
    else:
        br = db.query(BatchRun).filter(BatchRun.id == batch_run_id).first()

    db.close()

    log(f"=== BATCH #{batch_run_id} INICIADO ===")
    log(f"Config: top_n={top_n_per_source}, min_videos={min_videos_before_stream}, "
        f"category={category_filter or 'todas'}, stream={stream_after}")

    try:
        # ── 2. Fetch por fonte ────────────────────────────────────────────────
        log("Buscando artigos por fonte...")
        from aggregator.smart_fetcher import fetch_top_per_source
        article_ids = fetch_top_per_source(
            top_n=top_n_per_source,
            category_filter=category_filter,
            log=log,
        )
        _update_batch(batch_run_id, articles_fetched=len(article_ids))
        log(f"Total coletado: {len(article_ids)} artigos")

        if not article_ids:
            log("Nenhum artigo coletado — abortando batch")
            _finish_batch(batch_run_id, "failed")
            return batch_run_id

        # ── 3. Agrupamento por evento ─────────────────────────────────────────
        log("Agrupando por evento (dedup IA)...")
        from aggregator.smart_fetcher import group_articles_by_event, select_canonical_article
        groups = group_articles_by_event(article_ids, log=log)
        _update_batch(batch_run_id, events_found=len(groups))
        log(f"Eventos únicos identificados: {len(groups)}")

        # Seleciona o melhor artigo de cada grupo
        canonical_ids = []
        for group in groups:
            best_id = select_canonical_article(group)
            canonical_ids.append(best_id)

        log(f"Artigos canônicos selecionados: {len(canonical_ids)}")

        # ── 3b. Sequência natural por IA ──────────────────────────────────────
        log("Ordenando sequência das notícias por IA...")
        from aggregator.smart_fetcher import ai_sequence_articles
        canonical_ids = ai_sequence_articles(canonical_ids, log=log)

        # ── 4. Gera episódios ─────────────────────────────────────────────────
        log(f"Gerando {len(canonical_ids)} episódios...")
        from video.pipeline import generate_episode_for_article

        # Gera episódios em paralelo (máximo 2), mas preserva a ordem da sequência
        sem = asyncio.Semaphore(2)
        # results_by_pos[i] = (ep_id, Path) ou None
        results_by_pos: dict[int, tuple] = {}

        async def gen_one(art_id: int, pos: int):
            async with sem:
                log(f"  [{pos+1}/{len(canonical_ids)}] Gerando episódio para artigo {art_id}...")
                ep_id = await generate_episode_for_article(art_id)
                if ep_id:
                    db2 = get_session_factory()()
                    try:
                        ep = db2.query(Episode).filter(Episode.id == ep_id).first()
                        if ep and ep.video_path:
                            p = Path(ep.video_path)
                            if p.exists():
                                ep.batch_run_id = batch_run_id
                                db2.commit()
                                log(f"    ✓ Episódio {ep_id} pronto ({p.stat().st_size // 1024}KB)")
                                results_by_pos[pos] = (ep_id, p)
                                return
                    finally:
                        db2.close()
                log(f"    ✗ Falha no artigo {art_id}")

        await asyncio.gather(*[gen_one(aid, i) for i, aid in enumerate(canonical_ids)])

        # Reconstrói listas na ordem correta da sequência
        episode_paths = []
        episode_ids = []
        for i in range(len(canonical_ids)):
            if i in results_by_pos:
                ep_id, p = results_by_pos[i]
                episode_ids.append(ep_id)
                episode_paths.append(p)

        _update_batch(batch_run_id, episodes_generated=len(episode_paths))
        log(f"Episódios gerados: {len(episode_paths)}/{len(canonical_ids)}")

        if len(episode_paths) < min_videos_before_stream:
            log(f"Insuficiente ({len(episode_paths)} < {min_videos_before_stream}) — não inicia stream")
            _finish_batch(batch_run_id, "done" if episode_paths else "failed")
            return batch_run_id

        # ── 5. Concatena master video ─────────────────────────────────────────
        log("Concatenando episódios com vinheta...")
        from video.concat import build_master_video
        from run_channel import generate_vignette

        vignette_path = settings.video_output_path.parent / "assets" / "vignette.mp4"
        if not vignette_path.exists():
            log("Gerando vinheta de transição...")
            vignette_path = generate_vignette()

        master_dir = settings.video_output_path / f"batch_{batch_run_id}"
        master_dir.mkdir(parents=True, exist_ok=True)
        master_path = master_dir / "master.mp4"

        result = build_master_video(episode_paths, master_path, vignette_path)
        if result:
            size_mb = master_path.stat().st_size / (1024 * 1024)
            log(f"Master video pronto: {master_path} ({size_mb:.1f}MB)")
            _update_batch(batch_run_id, master_video_path=str(master_path))
        else:
            log("Falha na concatenação — transmitindo episódios separados")

        # ── 6. Inicia stream ──────────────────────────────────────────────────
        if stream_after and settings.youtube_stream_key:
            video_to_stream = result or episode_paths[0]
            log(f"Iniciando transmissão: {video_to_stream.name}")
            from stream.streamer import stream_video
            import threading
            threading.Thread(
                target=stream_video,
                args=(video_to_stream,),
                daemon=True,
                name=f"stream-batch-{batch_run_id}",
            ).start()
            _update_batch(batch_run_id, stream_started=True)
            log("Transmissão iniciada em background")
        elif stream_after:
            log("YOUTUBE_STREAM_KEY não configurada — stream não iniciado")

        _finish_batch(batch_run_id, "done")
        log(f"=== BATCH #{batch_run_id} CONCLUÍDO ===")
        return batch_run_id

    except Exception as e:
        logger.error(f"Batch #{batch_run_id} falhou: {e}", exc_info=True)
        log(f"ERRO: {e}")
        _finish_batch(batch_run_id, "failed")
        return batch_run_id


def _update_batch(batch_run_id: int, **kwargs):
    db = get_session_factory()()
    try:
        br = db.query(BatchRun).filter(BatchRun.id == batch_run_id).first()
        if br:
            for k, v in kwargs.items():
                setattr(br, k, v)
            db.commit()
    finally:
        db.close()


def _finish_batch(batch_run_id: int, status: str):
    db = get_session_factory()()
    try:
        br = db.query(BatchRun).filter(BatchRun.id == batch_run_id).first()
        if br:
            br.status = status
            br.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
