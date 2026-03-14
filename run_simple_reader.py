#!/usr/bin/env python3
"""
Leitor Simples de Notícias — Brasil24
======================================
Modo sem IA: captura as notícias mais importantes, lê o artigo completo
e gera áudio direto do conteúdo, sem interpretação ou diálogos.

Uso:
    python run_simple_reader.py                    # top 5 artigos
    python run_simple_reader.py --top 3            # top 3 artigos
    python run_simple_reader.py --id 42            # artigo específico
    python run_simple_reader.py --top 5 --music    # com música de fundo suave
    python run_simple_reader.py --fetch            # busca notícias antes de gerar
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Garante que o projeto esteja no path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("leitor_simples")


async def run_fetch_pipeline():
    """Busca e prepara artigos antes de gerar os áudios."""
    logger.info("Buscando novas notícias...")
    from aggregator.feed_fetcher import fetch_all_feeds
    from aggregator.scraper import scrape_pending
    from aggregator.deduplicator import deduplicate_articles
    from aggregator.ranker import rank_articles

    count = fetch_all_feeds()
    logger.info(f"  {count} artigos buscados dos feeds")

    scraped = scrape_pending(limit=30)
    logger.info(f"  {scraped} artigos com conteúdo extraído")

    dedup = deduplicate_articles()
    logger.info(f"  {dedup} duplicatas removidas")

    ranked = rank_articles()
    logger.info(f"  {ranked} artigos classificados por importância")


async def main():
    parser = argparse.ArgumentParser(
        description="Leitor Simples de Notícias — gera áudio sem IA"
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Número de artigos mais importantes a processar (padrão: 5)"
    )
    parser.add_argument(
        "--id", type=int, dest="article_id", default=None,
        help="Processar um artigo específico pelo ID"
    )
    parser.add_argument(
        "--music", action="store_true",
        help="Adicionar música de fundo suave ao áudio"
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Buscar notícias dos feeds antes de gerar áudio"
    )
    args = parser.parse_args()

    # Inicializa banco de dados
    from database.db import init_db
    init_db()

    # Busca notícias se solicitado
    if args.fetch:
        await run_fetch_pipeline()

    print()
    print("=" * 60)
    print("  LEITOR SIMPLES — Sem IA, sem diálogos, apenas notícias")
    print("=" * 60)

    if args.article_id:
        # Modo artigo específico
        from reader.reader_pipeline import generate_simple_audio
        logger.info(f"Gerando leitura para artigo ID={args.article_id}")
        audio = await generate_simple_audio(args.article_id, with_music=args.music)
        if audio:
            print(f"\n✓ Áudio gerado: {audio}")
            print(f"  Para ouvir: mpv {audio}  |  vlc {audio}  |  ffplay {audio}")
        else:
            print(f"\n✗ Falha ao gerar áudio para artigo {args.article_id}")
            sys.exit(1)
    else:
        # Modo top N artigos
        from reader.reader_pipeline import process_top_articles_simple
        logger.info(f"Gerando leitura para top {args.top} artigos...")
        results = await process_top_articles_simple(n=args.top, with_music=args.music)

        print(f"\nResultados ({len(results)} artigos):\n")
        ok_count = 0
        for r in results:
            status = "✓" if r["success"] else "✗"
            category = f"[{r['category']}]" if r["category"] else ""
            print(f"  {status} {category} {r['title'][:55]}")
            if r["success"]:
                print(f"      → {r['audio_path']}")
                ok_count += 1
            else:
                print(f"      → Falha na geração")

        print(f"\n{ok_count}/{len(results)} áudios gerados com sucesso.")

        if ok_count == 0:
            print("\nNenhum artigo disponível. Tente:")
            print("  python run_simple_reader.py --fetch --top 5")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
