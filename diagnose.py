#!/usr/bin/env python3
"""
Diagnóstico completo do pipeline Brasil24.
Testa cada etapa e mostra onde falha.

Uso: venv/bin/python diagnose.py [--step STEP]
     venv/bin/python diagnose.py --step tts
     venv/bin/python diagnose.py --step all   (padrão)
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Cores ANSI
GRN = "\033[92m"
RED = "\033[91m"
YEL = "\033[93m"
BLU = "\033[94m"
CYN = "\033[96m"
RST = "\033[0m"
BOLD = "\033[1m"

OK   = f"{GRN}✓ OK{RST}"
FAIL = f"{RED}✗ FALHOU{RST}"
WARN = f"{YEL}⚠ AVISO{RST}"
SKIP = f"{YEL}— SKIP{RST}"

logging.basicConfig(level=logging.WARNING)  # silencia logs internos


def header(title: str):
    print(f"\n{BOLD}{BLU}{'═'*60}{RST}")
    print(f"{BOLD}{BLU}  {title}{RST}")
    print(f"{BOLD}{BLU}{'═'*60}{RST}")


def step(name: str, ok: bool, detail: str = ""):
    status = OK if ok else FAIL
    print(f"  {status}  {name}")
    if detail:
        for line in detail.splitlines():
            print(f"        {CYN}{line}{RST}")


def run_cmd(cmd: list) -> tuple[bool, str, str]:
    """Roda comando, retorna (success, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Ambiente
# ══════════════════════════════════════════════════════════════════════════════

def check_environment():
    header("1. AMBIENTE E DEPENDÊNCIAS")

    # Python
    v = sys.version.split()[0]
    step("Python", True, v)

    # Virtualenv
    in_venv = sys.prefix != sys.base_prefix
    step("Virtualenv ativo", in_venv, sys.prefix if in_venv else "Use: venv/bin/python diagnose.py")

    # Pacotes críticos
    packages = [
        ("fastapi", "fastapi"),
        ("edge_tts", "edge-tts"),
        ("gtts", "gtts"),
        ("moviepy", "moviepy"),
        ("feedparser", "feedparser"),
        ("sqlalchemy", "sqlalchemy"),
        ("anthropic", "anthropic"),
        ("yaml", "pyyaml"),
        ("datasketch", "datasketch"),
        ("PIL", "Pillow"),
        ("numpy", "numpy"),
    ]
    for mod, pkg in packages:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            step(f"  {pkg}", True, ver)
        except ImportError:
            step(f"  {pkg}", False, f"pip install {pkg}")

    # ffmpeg / ffprobe
    for tool in ["ffmpeg", "ffprobe"]:
        ok, out, _ = run_cmd([tool, "-version"])
        ver = out.splitlines()[0] if out else "não encontrado"
        step(f"  {tool}", ok, ver[:60])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Configuração
# ══════════════════════════════════════════════════════════════════════════════

def check_config():
    header("2. CONFIGURAÇÃO (.env / settings)")

    try:
        from config.settings import settings

        step("settings carregado", True)

        ai_key = bool(settings.anthropic_api_key)
        yt_key = bool(settings.youtube_stream_key)
        step("ANTHROPIC_API_KEY", ai_key, "configurada" if ai_key else "não configurada (usa fallback)")
        step("YOUTUBE_STREAM_KEY", yt_key, "configurada" if yt_key else "não configurada (sem stream)")
        step("AI_PROVIDER", True, settings.ai_provider)
        step("DB path", True, settings.db_path)
        step("Video output", True, str(settings.video_output_path))

        # Diretórios
        out = settings.video_output_path
        out.mkdir(parents=True, exist_ok=True)
        step("  video/output criado", True, str(out))

    except Exception as e:
        step("settings", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Banco de Dados
# ══════════════════════════════════════════════════════════════════════════════

def check_database():
    header("3. BANCO DE DADOS (SQLite)")

    try:
        from database.db import init_db, get_session_factory
        from database.models import Article, Episode, BatchRun
        init_db()
        step("init_db()", True)

        db = get_session_factory()()
        n_art = db.query(Article).count()
        n_ep  = db.query(Episode).count()
        n_br  = db.query(BatchRun).count()
        n_vid = db.query(Episode).filter(Episode.video_path != None).count()
        db.close()

        step("Artigos no banco", True, f"{n_art} artigos")
        step("Episódios no banco", True, f"{n_ep} episódios ({n_vid} com vídeo)")
        step("Batch runs", True, f"{n_br} runs")
    except Exception as e:
        step("Banco de dados", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — AI
# ══════════════════════════════════════════════════════════════════════════════

def check_ai():
    header("4. PROVEDOR DE IA")

    try:
        from ai.client import is_available, provider_info, chat
        info = provider_info()
        avail = is_available()
        step(f"Provedor: {info.get('provider','?')}", avail,
             f"model={info.get('model','?')}  url={info.get('base_url','')}")

        if avail:
            print(f"  {YEL}Testando chamada real de IA...{RST}")
            t0 = time.time()
            resp = chat(
                system="Você é um assistente. Responda SOMENTE com: OK",
                user="Diga OK",
                max_tokens=10,
            )
            elapsed = time.time() - t0
            ok = "ok" in (resp or "").lower()
            step("Resposta da IA", ok, f"'{resp}' ({elapsed:.1f}s)")
        else:
            step("Chamada IA", False, "Provedor indisponível — verifique API key / Ollama")
    except Exception as e:
        step("IA", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — RSS Fetch
# ══════════════════════════════════════════════════════════════════════════════

def check_fetch():
    header("5. COLETA DE NOTÍCIAS (RSS)")

    try:
        import yaml
        from config.settings import settings
        with open(settings.sources_path) as f:
            cfg = yaml.safe_load(f)

        feeds = [fd for fd in cfg.get("feeds", []) if fd.get("enabled", True)]
        step("Feeds habilitados", True, f"{len(feeds)} fontes")

        import feedparser
        ok_count, fail_count = 0, 0
        for fd in feeds[:3]:  # testa só os primeiros 3
            try:
                t0 = time.time()
                parsed = feedparser.parse(fd["url"])
                elapsed = time.time() - t0
                n = len(parsed.entries)
                if n > 0:
                    ok_count += 1
                    step(f"  {fd['name']}", True, f"{n} entradas ({elapsed:.1f}s)")
                else:
                    fail_count += 1
                    step(f"  {fd['name']}", False, "0 entradas retornadas")
            except Exception as e:
                fail_count += 1
                step(f"  {fd['name']}", False, str(e))

        step("Fetch de feeds", ok_count > 0, f"{ok_count} OK, {fail_count} falhas")
    except Exception as e:
        step("Fetch", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — TTS
# ══════════════════════════════════════════════════════════════════════════════

def check_tts():
    header("6. TTS (SÍNTESE DE VOZ)")

    TEXT_ANA    = "Boa tarde, eu sou Ana Silva do Brasil24."
    TEXT_CARLOS = "Como analista, vejo que esta notícia é relevante."

    # edge-tts
    print(f"  {YEL}Testando edge-tts...{RST}")
    try:
        import edge_tts

        async def _test_edge(text, voice):
            out = Path(tempfile.mktemp(suffix=".mp3"))
            try:
                comm = edge_tts.Communicate(text=text, voice=voice)
                await comm.save(str(out))
                ok = out.exists() and out.stat().st_size > 100
                out.unlink(missing_ok=True)
                return ok
            except Exception as e:
                out.unlink(missing_ok=True)
                return False, str(e)

        ok_ana    = asyncio.run(_test_edge(TEXT_ANA, "pt-BR-FranciscaNeural"))
        ok_carlos = asyncio.run(_test_edge(TEXT_CARLOS, "pt-BR-AntonioNeural"))
        step("edge-tts Ana (FranciscaNeural)", ok_ana,
             "OK" if ok_ana else "403 bloqueado por IP de VM — gTTS será usado como fallback")
        step("edge-tts Carlos (AntonioNeural)", ok_carlos,
             "OK" if ok_carlos else "403 bloqueado por IP de VM — gTTS será usado como fallback")
    except ImportError:
        step("edge-tts", False, "não instalado")
    except Exception as e:
        step("edge-tts", False, str(e))

    # gTTS
    print(f"  {YEL}Testando gTTS (fallback)...{RST}")
    try:
        from tts.voice_engine import _generate_gtts, GTTS_AVAILABLE
        if not GTTS_AVAILABLE:
            step("gTTS", False, "não instalado: pip install gtts")
        else:
            out_ana    = Path(tempfile.mktemp(suffix=".mp3"))
            out_carlos = Path(tempfile.mktemp(suffix=".mp3"))
            ok_ana    = _generate_gtts(TEXT_ANA, "ana", "geral", out_ana)
            ok_carlos = _generate_gtts(TEXT_CARLOS, "carlos", "economia", out_carlos)
            sz_ana    = out_ana.stat().st_size if ok_ana and out_ana.exists() else 0
            sz_carlos = out_carlos.stat().st_size if ok_carlos and out_carlos.exists() else 0
            out_ana.unlink(missing_ok=True)
            out_carlos.unlink(missing_ok=True)
            step("gTTS Ana",    ok_ana,    f"{sz_ana:,} bytes")
            step("gTTS Carlos", ok_carlos, f"{sz_carlos:,} bytes")
    except Exception as e:
        step("gTTS", False, str(e))

    # Pipeline completo (com fallback)
    print(f"  {YEL}Testando pipeline TTS completo (edge → gTTS)...{RST}")
    try:
        from tts.voice_engine import generate_speech_sync
        out = Path(tempfile.mktemp(suffix=".mp3"))
        ok = generate_speech_sync(TEXT_ANA, "ana", out)
        sz = out.stat().st_size if ok and out.exists() else 0
        out.unlink(missing_ok=True)
        step("Pipeline TTS completo", ok, f"{sz:,} bytes gerados")
    except Exception as e:
        step("Pipeline TTS", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Geração de Vídeo
# ══════════════════════════════════════════════════════════════════════════════

def check_video():
    header("7. GERAÇÃO DE VÍDEO (MoviePy)")

    try:
        import numpy as np
        from PIL import Image
        step("numpy + Pillow", True)

        from moviepy.editor import VideoClip
        step("moviepy", True)

        # Gera 2s de vídeo de teste
        print(f"  {YEL}Gerando 2s de vídeo de teste...{RST}")
        out = Path(tempfile.mktemp(suffix=".mp4"))
        W, H, FPS = 1280, 720, 24

        def make_frame(t):
            frame = np.zeros((H, W, 3), dtype=np.uint8)
            frame[:, :, 2] = int(255 * (t / 2))  # azul crescente
            return frame

        t0 = time.time()
        clip = VideoClip(make_frame, duration=2)
        clip.write_videofile(str(out), fps=FPS, codec="libx264",
                             audio=False, logger=None, verbose=False)
        elapsed = time.time() - t0
        ok = out.exists() and out.stat().st_size > 1000
        sz = out.stat().st_size if ok else 0
        out.unlink(missing_ok=True)
        step("Renderização 2s", ok, f"{sz:,} bytes em {elapsed:.1f}s")

    except Exception as e:
        step("Vídeo", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Pipeline Completo (artigo → áudio)
# ══════════════════════════════════════════════════════════════════════════════

def check_full_pipeline():
    header("8. PIPELINE: ARTIGO → ÁUDIO")

    try:
        from database.db import init_db, get_session_factory
        from database.models import Article
        init_db()

        db = get_session_factory()()
        art = db.query(Article).filter(Article.content != None).first()
        db.close()

        if not art:
            step("Artigo de teste", False, "Banco vazio — rode primeiro: curl -X POST http://localhost:8000/api/admin/fetch")
            return

        step("Artigo encontrado", True, f"ID={art.id}: {art.title[:60]}")

        # Sumarização
        print(f"  {YEL}Testando sumarização...{RST}")
        try:
            from ai.summarizer import summarize_article
            from ai.client import is_available
            if is_available():
                summary = summarize_article(art.content[:500], art.category or "geral")
                ok = bool(summary and len(summary) > 20)
                step("Sumarização", ok, (summary or "")[:80] + "...")
            else:
                step("Sumarização", False, "IA indisponível")
        except Exception as e:
            step("Sumarização", False, str(e))

        # Diálogo
        print(f"  {YEL}Testando geração de diálogo...{RST}")
        try:
            from ai.dialogue_generator import generate_dialogue
            from ai.client import is_available
            if is_available():
                summary_text = art.summary or art.content[:200]
                script = generate_dialogue(art.title, summary_text, art.category or "geral")
                ok = isinstance(script, list) and len(script) > 0
                step("Geração de diálogo", ok,
                     f"{len(script)} falas" if ok else "script vazio ou inválido")
                if ok:
                    step("  Primeira fala", True,
                         f"{script[0].get('persona','?')}: {str(script[0].get('text',''))[:60]}")
            else:
                step("Diálogo", False, "IA indisponível")
        except Exception as e:
            step("Diálogo", False, str(e))

        # TTS de uma fala
        print(f"  {YEL}Testando TTS de uma fala...{RST}")
        try:
            from tts.voice_engine import generate_speech_sync
            out = Path(tempfile.mktemp(suffix=".mp3"))
            ok = generate_speech_sync("Esta é uma notícia de teste.", "ana", out)
            sz = out.stat().st_size if ok and out.exists() else 0
            out.unlink(missing_ok=True)
            step("TTS de fala", ok, f"{sz:,} bytes")
        except Exception as e:
            step("TTS", False, str(e))

    except Exception as e:
        step("Pipeline", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Processos e Portas
# ══════════════════════════════════════════════════════════════════════════════

def check_processes():
    header("9. PROCESSOS E PORTAS")

    # uvicorn
    ok, out, _ = run_cmd(["pgrep", "-a", "uvicorn"])
    step("uvicorn rodando", ok, out[:100] if ok else "não está rodando")

    # pm2
    ok_pm2, out_pm2, _ = run_cmd(["pm2", "list"])
    step("pm2", ok_pm2, "" if not ok_pm2 else "")
    if ok_pm2:
        for line in out_pm2.splitlines():
            if "agregado" in line.lower() or "brasil" in line.lower() or "online" in line.lower():
                print(f"    {CYN}{line.strip()}{RST}")

    # Porta 8000
    ok, out, _ = run_cmd(["ss", "-tlnp"])
    porta_ok = ":8000" in (out or "")
    step("Porta 8000 aberta", porta_ok, "servidor respondendo" if porta_ok else "nada ouvindo em 8000")

    # API health
    ok_curl, out_curl, _ = run_cmd(["curl", "-s", "--max-time", "5", "http://localhost:8000/api/health"])
    step("API /health", ok_curl and out_curl.startswith("{"),
         out_curl[:120] if out_curl else "sem resposta")

    # Disco
    ok, out, _ = run_cmd(["df", "-h", "."])
    if ok:
        lines = out.splitlines()
        if len(lines) >= 2:
            step("Disco", True, lines[1])

    # Memória
    ok, out, _ = run_cmd(["free", "-h"])
    if ok:
        for line in out.splitlines():
            if line.startswith("Mem"):
                step("Memória", True, line)
                break


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

STEPS = {
    "env":       check_environment,
    "config":    check_config,
    "database":  check_database,
    "ai":        check_ai,
    "fetch":     check_fetch,
    "tts":       check_tts,
    "video":     check_video,
    "pipeline":  check_full_pipeline,
    "processes": check_processes,
}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Diagnóstico do pipeline Brasil24")
    parser.add_argument("--step", default="all",
                        choices=list(STEPS.keys()) + ["all"],
                        help="Qual etapa testar (padrão: all)")
    args = parser.parse_args()

    print(f"\n{BOLD}{'═'*60}")
    print(f"  BRASIL24 — DIAGNÓSTICO DO PIPELINE")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*60}{RST}")

    if args.step == "all":
        for fn in STEPS.values():
            try:
                fn()
            except Exception as e:
                print(f"{RED}Erro inesperado na etapa: {e}{RST}")
    else:
        STEPS[args.step]()

    print(f"\n{BOLD}{BLU}{'═'*60}{RST}")
    print(f"{BOLD}  Diagnóstico concluído.{RST}")
    print(f"{BLU}{'═'*60}{RST}\n")
