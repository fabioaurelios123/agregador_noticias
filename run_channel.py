"""
Brasil24 — Canal 24/7
Executa em paralelo:
  1. Servidor web (FastAPI)
  2. Gerador contínuo de vídeos (top N notícias a cada ciclo)
  3. Streamer contínuo para YouTube com replay automático e vinheta de transição
  4. Limpeza automática de vídeos com mais de 1 dia

Uso:
    venv/bin/python run_channel.py                  # tudo junto
    venv/bin/python run_channel.py --no-stream      # sem YouTube (só gera vídeos)
    venv/bin/python run_channel.py --no-server      # sem web server
    venv/bin/python run_channel.py --no-generate    # só stream (videos já gerados)
"""
import argparse
import asyncio
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("channel")

# ── Configurações ──────────────────────────────────────────────────────────────

TOP_N           = 5      # quantas notícias gerar por ciclo
FETCH_EVERY     = 900    # buscar novas notícias a cada 15 min (segundos)
STREAM_WAIT     = 10     # segundos entre tentativas quando fila vazia
MIN_QUEUE       = 1      # mínimo de vídeos prontos antes de iniciar stream
CLEANUP_OLDER   = 1      # remover episódios com mais de N dias
CLEANUP_EVERY   = 3600   # rodar limpeza a cada 1 hora (segundos)
VIGNETTE_SECS   = 4      # duração da vinheta de transição (segundos)


# ── Utilitários de banco ────────────────────────────────────────────────────────

def _get_db():
    from database.db import get_session_factory
    return get_session_factory()()


# ══════════════════════════════════════════════════════════════════════════════
# VINHETA DE TRANSIÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def generate_vignette() -> Path:
    """
    Gera um vídeo curto de transição (VIGNETTE_SECS segundos) com a identidade
    visual do Brasil24. Roda uma vez na inicialização e salva em video/assets/.
    """
    from config.settings import settings
    out_path = settings.video_output_path.parent / "assets" / "vignette.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        logger.info(f"Vinheta já existe: {out_path}")
        return out_path

    logger.info("Gerando vinheta de transição...")

    try:
        import math
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from moviepy.editor import VideoClip, AudioFileClip

        W, H = 1920, 1080
        FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        def _font(path, size):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                return ImageFont.load_default()

        BG   = (8, 10, 18)
        RED  = (220, 38, 38)
        GOLD = (232, 168, 56)
        WHITE = (240, 242, 250)
        BLUE  = (96, 165, 250)

        duration = float(VIGNETTE_SECS)
        f_brand = _font(FONT_BOLD, 160)
        f_sub   = _font(FONT_REG,  36)

        def make_frame(t):
            # Progresso 0..1
            prog = t / duration

            # Fade in nos primeiros 0.5s, fade out nos últimos 0.5s
            fade = min(t / 0.5, 1.0, (duration - t) / 0.5)

            img = Image.new("RGB", (W, H), BG)
            draw = ImageDraw.Draw(img)

            # Gradiente radial animado
            cx, cy = W // 2, H // 2
            pulse = (math.sin(t * math.pi * 2) + 1) / 2
            for r in range(int(420 + pulse * 60), 0, -15):
                a = int(30 * (1 - r / 500) * fade)
                if a > 0:
                    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)],
                                 outline=(*BLUE, a), width=1)

            # Linhas diagonais em movimento
            speed_off = int(t * 40) % 160
            for x in range(-H, W + H, 160):
                draw.line([(x + speed_off, 0), (x + speed_off + H, H)],
                          fill=(*RED, 10), width=2)

            # Faixa vermelha lateral animada (slide in da esquerda)
            bar_w = int(12 * min(t / 0.3, 1.0))
            if bar_w > 0:
                draw.rectangle([(0, 0), (bar_w, H)], fill=RED)

            # Escala do logo: zoom in de 0.6 a 1.0 nos primeiros 0.8s
            logo_scale = 0.6 + 0.4 * min(t / 0.8, 1.0)

            # Logo BRASIL24 centralizado
            brand = "BRASIL"
            num   = "24"
            f_b   = _font(FONT_BOLD, int(160 * logo_scale))
            f_n   = _font(FONT_BOLD, int(160 * logo_scale))
            f_s   = _font(FONT_REG,  int(32 * logo_scale))

            bw = int(draw.textlength(brand, font=f_b)) if hasattr(draw, "textlength") else 450
            nw = int(draw.textlength(num,   font=f_n)) if hasattr(draw, "textlength") else 180
            tw = bw + nw + 8
            x0 = (W - tw) // 2
            y0 = cy - int(90 * logo_scale)

            # Sombra
            alpha_logo = int(255 * fade)
            draw.text((x0 + 4, y0 + 4), brand, font=f_b,
                      fill=(0, 0, 0))
            draw.text((x0, y0), brand, font=f_b, fill=WHITE)
            draw.text((x0 + bw + 8, y0), num, font=f_n, fill=GOLD)

            # Linha vermelha sob o logo
            sep_y = y0 + int(170 * logo_scale)
            line_prog = min((t - 0.3) / 0.4, 1.0) if t > 0.3 else 0
            if line_prog > 0:
                line_w = int(tw * line_prog)
                draw.rectangle([(x0, sep_y), (x0 + line_w, sep_y + 3)], fill=RED)

            # Tagline aparece depois de 0.7s
            if t > 0.7:
                tag = "NOTÍCIAS EM TEMPO REAL"
                tag_fade = min((t - 0.7) / 0.4, 1.0) * fade
                tw2 = int(draw.textlength(tag, font=f_s)) if hasattr(draw, "textlength") else 400
                gray_val = int(140 * tag_fade)
                draw.text(((W - tw2) // 2, sep_y + 14), tag, font=f_s,
                          fill=(gray_val, gray_val + 10, gray_val + 20))

            # Faixa inferior
            draw.rectangle([(0, H - 60), (W, H)], fill=(6, 8, 16))
            draw.rectangle([(0, H - 60), (W, H - 57)], fill=RED)

            # Ticker vazio com "BRASIL24"
            f_tick = _font(FONT_BOLD, 22)
            draw.text((20, H - 48), "● BRASIL24 — NOTÍCIAS AO VIVO ●", font=f_tick,
                      fill=(120, 130, 150))

            # Fade to black nas bordas
            arr = np.array(img, dtype=float)
            for y in range(H):
                fx = np.arange(W)
                dy = min(y, H - y) / (H * 0.15)
                dx = np.minimum(fx, W - fx) / (W * 0.15)
                alpha = np.clip(np.minimum(dx, dy), 0, 1) * fade
                arr[y] = arr[y] * alpha[:, None]

            return arr.astype(np.uint8)

        clip = VideoClip(make_frame, duration=duration)
        clip.write_videofile(
            str(out_path),
            fps=24,
            codec="libx264",
            audio=False,
            preset="veryfast",
            logger=None,
        )
        clip.close()
        logger.info(f"Vinheta gerada: {out_path}")
        return out_path

    except Exception as e:
        logger.error(f"Falha ao gerar vinheta: {e}", exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# LIMPEZA DE EPISÓDIOS ANTIGOS
# ══════════════════════════════════════════════════════════════════════════════

def cleanup_old_episodes():
    """
    Remove do filesystem episódios criados há mais de CLEANUP_OLDER dias.
    Mantém o registro no banco (com video_path=None) para histórico.
    """
    from database.models import Episode

    cutoff = datetime.utcnow() - timedelta(days=CLEANUP_OLDER)
    db = _get_db()
    try:
        old_eps = (
            db.query(Episode)
            .filter(Episode.created_at < cutoff, Episode.video_path != None)
            .all()
        )
        removed = 0
        freed_mb = 0
        for ep in old_eps:
            ep_dir = Path(ep.video_path).parent if ep.video_path else None
            if ep_dir and ep_dir.exists():
                size = sum(f.stat().st_size for f in ep_dir.rglob("*") if f.is_file())
                shutil.rmtree(ep_dir, ignore_errors=True)
                freed_mb += size / (1024 * 1024)
                removed += 1
                logger.info(f"  Removido: {ep_dir.name} ({size // 1024}KB)")

            # Nulifica paths no banco (mantém registro histórico)
            ep.video_path = None
            ep.audio_path = None

        if old_eps:
            db.commit()
            logger.info(f"Limpeza: {removed} episódio(s) removidos, {freed_mb:.1f}MB liberados")
        else:
            logger.debug("Limpeza: nenhum episódio antigo para remover")

    except Exception as e:
        logger.error(f"Erro na limpeza: {e}", exc_info=True)
    finally:
        db.close()


def cleanup_loop():
    """Thread que roda a limpeza periodicamente."""
    while True:
        time.sleep(CLEANUP_EVERY)
        logger.info("=== LIMPEZA DE EPISÓDIOS ANTIGOS ===")
        cleanup_old_episodes()


# ══════════════════════════════════════════════════════════════════════════════
# WORKER 1: SERVIDOR WEB
# ══════════════════════════════════════════════════════════════════════════════

def _uvicorn_path():
    venv = Path(sys.executable).parent
    uv = venv / "uvicorn"
    return str(uv) if uv.exists() else "uvicorn"


# ══════════════════════════════════════════════════════════════════════════════
# WORKER 2: GERADOR DE VÍDEOS
# ══════════════════════════════════════════════════════════════════════════════

async def video_generator_loop():
    from aggregator.feed_fetcher import fetch_all_feeds
    from aggregator.ranker import get_top_articles
    from video.pipeline import generate_episode_for_article

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"=== CICLO DE GERAÇÃO #{cycle} ===")

        try:
            count = fetch_all_feeds()
            logger.info(f"Feeds atualizados — {count} novos artigos")
        except Exception as e:
            logger.error(f"Erro ao buscar feeds: {e}")

        articles = get_top_articles(n=TOP_N)
        if not articles:
            logger.info("Nenhum artigo novo para gerar — aguardando próximo ciclo")
        else:
            logger.info(f"Gerando vídeos para {len(articles)} artigos...")
            for i, article in enumerate(articles, 1):
                logger.info(f"[{i}/{len(articles)}] {article.title[:70]}")
                try:
                    ep_id = await generate_episode_for_article(article.id)
                    if ep_id:
                        logger.info(f"  ✓ Episódio {ep_id} pronto")
                    else:
                        logger.warning(f"  ✗ Falha no artigo {article.id}")
                except Exception as e:
                    logger.error(f"  ✗ Erro no artigo {article.id}: {e}", exc_info=True)

        logger.info(f"Próximo ciclo em {FETCH_EVERY // 60} minutos...")
        await asyncio.sleep(FETCH_EVERY)


# ══════════════════════════════════════════════════════════════════════════════
# WORKER 3: STREAMER YOUTUBE  (com replay automático e vinheta)
# ══════════════════════════════════════════════════════════════════════════════

def get_next_video() -> tuple[Path | None, str]:
    """
    Estratégia de seleção do próximo vídeo para transmissão:
      1. Novo episódio não transmitido ainda (LIVE)
      2. Se fila vazia → replay do episódio mais antigo disponível (round-robin)
      3. Se nenhum vídeo existe ainda → None (aguarda)
    """
    from database.models import Episode

    db = _get_db()
    try:
        # 1. Tenta pegar episódio novo (não transmitido)
        ep = (
            db.query(Episode)
            .filter(Episode.streamed == False, Episode.video_path != None)
            .order_by(Episode.created_at.asc())
            .first()
        )
        if ep and Path(ep.video_path).exists():
            ep.streamed = True
            db.commit()
            return Path(ep.video_path), "LIVE"

        # 2. Fila vazia — replay: pega todos os episódios com vídeo disponível
        all_eps = (
            db.query(Episode)
            .filter(Episode.video_path != None)
            .order_by(Episode.created_at.desc())   # mais recente primeiro
            .all()
        )
        valid = [ep for ep in all_eps if ep.video_path and Path(ep.video_path).exists()]
        if valid:
            # Round-robin: usa o mais antigo da lista (vai rotacionando)
            chosen = valid[-1]
            # Reseta streamed para que continue na rotação
            chosen.streamed = False
            db.commit()
            return Path(chosen.video_path), "REPLAY"

        return None, "WAITING"

    finally:
        db.close()


def count_available_videos() -> int:
    """Conta vídeos com arquivo físico existente."""
    from database.models import Episode
    db = _get_db()
    try:
        eps = db.query(Episode).filter(Episode.video_path != None).all()
        return sum(1 for ep in eps if ep.video_path and Path(ep.video_path).exists())
    finally:
        db.close()


def stream_with_vignette(video_path: Path, vignette_path: Path | None):
    """Transmite vinheta (se disponível) seguida do vídeo principal."""
    from stream.streamer import stream_video

    if vignette_path and vignette_path.exists():
        logger.info(f"  → Vinheta de transição ({VIGNETTE_SECS}s)")
        stream_video(vignette_path)

    logger.info(f"  → Transmitindo: {video_path.parent.name}/{video_path.name}")
    return stream_video(video_path)


def stream_loop(vignette_path: Path | None = None):
    """
    Loop de streaming contínuo:
    - Aguarda ter pelo menos MIN_QUEUE vídeo(s) pronto(s) antes de começar
    - Transmite vinheta + episódio em sequência
    - Se fila de novos esgota, faz replay dos episódios existentes
    - Nunca para a transmissão enquanto houver pelo menos 1 vídeo disponível
    """
    from config.settings import settings

    if not settings.youtube_stream_key:
        logger.error("YOUTUBE_STREAM_KEY não configurada no .env — streaming desativado")
        return

    logger.info(f"Aguardando pelo menos {MIN_QUEUE} vídeo(s) pronto(s)...")
    while count_available_videos() < MIN_QUEUE:
        available = count_available_videos()
        logger.info(f"  Disponíveis: {available}/{MIN_QUEUE} — aguardando 30s...")
        time.sleep(30)

    logger.info("▶ Iniciando transmissão para YouTube!")

    while True:
        video_path, mode = get_next_video()

        if video_path:
            logger.info(f"[{mode}] {video_path.parent.name}")
            ok = stream_with_vignette(video_path, vignette_path)
            if not ok:
                logger.warning("Transmissão encerrada/falhou — continuando com próximo...")
                time.sleep(3)
        else:
            # Sem nenhum vídeo ainda
            logger.info(f"[WAITING] Nenhum vídeo disponível — aguardando {STREAM_WAIT}s...")
            time.sleep(STREAM_WAIT)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global TOP_N  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="Brasil24 — Canal 24/7")
    parser.add_argument("--no-server",   action="store_true", help="Não inicia o servidor web")
    parser.add_argument("--no-generate", action="store_true", help="Não gera novos vídeos")
    parser.add_argument("--no-stream",   action="store_true", help="Não transmite para o YouTube")
    parser.add_argument("--no-vignette", action="store_true", help="Sem vinheta de transição")
    parser.add_argument("--no-cleanup",  action="store_true", help="Sem limpeza automática")
    parser.add_argument("--top",         type=int, default=TOP_N,
                        help=f"Notícias por ciclo (padrão: {TOP_N})")
    args = parser.parse_args()
    TOP_N = args.top

    # ── Gerar vinheta de transição (uma vez) ──────────────────────────────────
    vignette_path = None
    if not args.no_stream and not args.no_vignette:
        vignette_path = generate_vignette()

    threads = []

    # ── Worker 1: Servidor web ─────────────────────────────────────────────────
    if not args.no_server:
        t = Thread(
            target=lambda: subprocess.run([_uvicorn_path(), "main:app", "--host", "0.0.0.0", "--port", "8000"]),
            daemon=True, name="web-server",
        )
        t.start()
        threads.append(t)
        logger.info("Servidor web: http://localhost:8000")

    # ── Worker 4: Limpeza automática ───────────────────────────────────────────
    if not args.no_cleanup:
        t = Thread(target=cleanup_loop, daemon=True, name="cleanup")
        t.start()
        threads.append(t)
        logger.info(f"Limpeza automática: episódios com >{CLEANUP_OLDER} dia(s) removidos a cada {CLEANUP_EVERY // 60}min")

    # ── Worker 3: Stream YouTube ───────────────────────────────────────────────
    if not args.no_stream:
        t = Thread(target=stream_loop, args=(vignette_path,), daemon=True, name="streamer")
        t.start()
        threads.append(t)

    # ── Worker 2: Gerador (asyncio — bloqueia o main thread) ──────────────────
    if not args.no_generate:
        try:
            asyncio.run(video_generator_loop())
        except KeyboardInterrupt:
            logger.info("Encerrando canal...")
    else:
        logger.info("Modo sem geração — transmitindo episódios existentes")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass

    logger.info("Canal encerrado.")


if __name__ == "__main__":
    main()
