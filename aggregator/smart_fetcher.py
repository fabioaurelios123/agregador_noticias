"""
Smart batch fetcher: coleta top N artigos por fonte e agrupa eventos similares via IA.
"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Callable, Optional

import feedparser
import yaml

from config.settings import settings
from database.db import get_session_factory
from database.models import Article

logger = logging.getLogger(__name__)


# ── Fetch top N por fonte ───────────────────────────────────────────────────────

def fetch_top_per_source(
    top_n: int = 5,
    category_filter: Optional[str] = None,
    log: Callable[[str], None] = logger.info,
) -> list[int]:
    """
    Para cada feed habilitado em sources.yaml, pega os top_n artigos mais recentes.
    Persiste novos artigos no banco. Retorna lista de article_ids coletados.
    """
    with open(settings.sources_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    feeds = cfg.get("feeds", [])
    keywords = cfg.get("keywords", {})

    if category_filter:
        feeds = [f for f in feeds if f.get("category_default") == category_filter]

    db = get_session_factory()()
    collected_ids = []

    try:
        for feed_cfg in feeds:
            if not feed_cfg.get("enabled", True):
                continue
            ids = _fetch_one_source(feed_cfg, top_n, db, keywords)
            collected_ids.extend(ids)
            log(f"  {feed_cfg['name']}: {len(ids)} artigos coletados")

        db.commit()
        log(f"Total: {len(collected_ids)} artigos de {len(feeds)} fontes")
        return collected_ids
    except Exception as e:
        db.rollback()
        logger.error(f"Erro no fetch por fonte: {e}")
        raise
    finally:
        db.close()


def _fetch_one_source(source_cfg: dict, top_n: int, db, keywords: dict) -> list[int]:
    """Parseia um feed RSS, persiste até top_n artigos novos, retorna ids."""
    try:
        feed = feedparser.parse(source_cfg["url"])
    except Exception as e:
        logger.warning(f"Falha ao parsear feed {source_cfg['name']}: {e}")
        return []

    ids = []
    for entry in feed.entries[:top_n]:
        url = entry.get("link") or entry.get("id", "")
        title = entry.get("title", "").strip()
        if not url or not title:
            continue

        # Verificar se já existe
        existing = db.query(Article).filter(Article.url == url).first()
        if existing:
            ids.append(existing.id)
            continue

        # Determinar categoria
        category = source_cfg.get("category_default", "geral")
        combined = (title + " " + entry.get("summary", "")).lower()
        for cat, kws in keywords.items():
            if any(kw in combined for kw in kws):
                category = cat
                break

        # Publicação
        pub_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_at = datetime(*entry.published_parsed[:6])
            except Exception:
                pass

        article = Article(
            source=source_cfg["name"],
            title=title,
            url=url,
            content=entry.get("summary", ""),
            category=category,
            score=source_cfg.get("weight", 1.0),
            fetched_at=datetime.utcnow(),
            published_at=pub_at,
        )
        db.add(article)
        try:
            db.flush()
            ids.append(article.id)
        except Exception:
            db.rollback()

    return ids


# ── Agrupamento de eventos por IA ───────────────────────────────────────────────

def group_articles_by_event(
    article_ids: list[int],
    log: Callable[[str], None] = logger.info,
) -> list[list[int]]:
    """
    Agrupa artigos que cobrem o mesmo evento usando MinHash + IA.
    Retorna lista de grupos (cada grupo = lista de article_ids).
    """
    if not article_ids:
        return []

    db = get_session_factory()()
    try:
        articles = db.query(Article).filter(Article.id.in_(article_ids)).all()
        articles_by_id = {a.id: a for a in articles}
    finally:
        db.close()

    # Fase 1: MinHash clustering
    clusters = _minhash_cluster(articles, threshold=0.5)
    log(f"MinHash: {len(articles)} artigos → {len(clusters)} grupos iniciais")

    # Fase 2: refinamento por IA (se disponível)
    from ai.client import is_available
    if is_available() and len(clusters) > 1:
        try:
            clusters = _ai_refine_clusters(clusters, articles_by_id, log)
            log(f"IA refinamento: {len(clusters)} grupos finais")
        except Exception as e:
            logger.warning(f"Refinamento IA falhou (usando MinHash): {e}")

    return clusters


def _minhash_cluster(articles, threshold: float = 0.5) -> list[list[int]]:
    """Agrupa artigos similares por título usando MinHash LSH."""
    try:
        from datasketch import MinHash, MinHashLSH

        lsh = MinHashLSH(threshold=threshold, num_perm=64)
        id_to_minhash = {}

        def _norm(text):
            return re.sub(r"[^\w\s]", "", text.lower())

        def _mh(text):
            m = MinHash(num_perm=64)
            words = _norm(text).split()
            shingles = {" ".join(words[i:i+2]) for i in range(len(words)-1)} or set(words)
            for s in shingles:
                m.update(s.encode())
            return m

        clusters = []
        used = set()

        for article in articles:
            m = _mh(article.title)
            id_to_minhash[article.id] = m

        for article in articles:
            if article.id in used:
                continue
            m = id_to_minhash[article.id]
            results = lsh.query(m)
            # results são chaves já inseridas similares; forma grupo com elas
            group = [article.id]
            for key in results:
                aid = int(key)
                if aid != article.id and aid not in used:
                    group.append(aid)
                    used.add(aid)
            lsh.insert(str(article.id), m)
            used.add(article.id)
            clusters.append(group)

        return clusters

    except ImportError:
        # Sem datasketch: cada artigo é seu próprio grupo
        return [[a.id] for a in articles]


def _ai_refine_clusters(
    clusters: list[list[int]],
    articles_by_id: dict,
    log: Callable,
) -> list[list[int]]:
    """Usa IA para confirmar/fundir grupos similares."""
    from ai.client import chat

    # Prepara lista compacta de grupos com títulos
    groups_info = []
    for i, group in enumerate(clusters):
        titles = [articles_by_id[aid].title[:80] for aid in group if aid in articles_by_id]
        groups_info.append({"group": i, "ids": group, "titles": titles})

    system = (
        "Você é um editor de notícias. Analise grupos de artigos e identifique "
        "quais cobrem exatamente o mesmo evento. Responda APENAS com JSON."
    )
    user = (
        f"Grupos de artigos:\n{json.dumps(groups_info, ensure_ascii=False, indent=2)}\n\n"
        "Retorne um JSON com os grupos fundidos. Se grupos cobrem o mesmo evento, "
        "funda-os. Formato: [[id1,id2],[id3],[id4,id5]] — arrays de article IDs."
        " Retorne APENAS o array JSON, sem explicação."
    )

    raw = chat(system=system, user=user, max_tokens=500)
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return clusters

    try:
        result = json.loads(match.group())
        # Valida que todos os IDs originais estão presentes
        all_orig = {aid for group in clusters for aid in group}
        all_new = {aid for group in result for aid in group}
        if not all_orig.issubset(all_new):
            return clusters
        return [group for group in result if group]
    except Exception:
        return clusters


def select_canonical_article(group: list[int]) -> int:
    """Seleciona o melhor artigo de um grupo (maior score)."""
    db = get_session_factory()()
    try:
        articles = db.query(Article).filter(Article.id.in_(group)).all()
        best = max(articles, key=lambda a: (a.score or 0))
        return best.id
    finally:
        db.close()


def ai_sequence_articles(
    article_ids: list[int],
    log: Callable[[str], None] = logger.info,
) -> list[int]:
    """
    Usa IA para ordenar os artigos canônicos em sequência natural de telejornal:
    - Notícia mais importante primeiro
    - Alternância de categorias (evita dois seguidos do mesmo tema)
    - Fluxo narrativo coerente (ex: política → economia → saúde → esporte)
    - Sem repetição temática consecutiva

    Fallback: heurística simples (pontuação × variedade de categoria) se IA indisponível.
    """
    if not article_ids or len(article_ids) <= 1:
        return article_ids

    db = get_session_factory()()
    try:
        articles = db.query(Article).filter(Article.id.in_(article_ids)).all()
        articles_by_id = {a.id: a for a in articles}
    finally:
        db.close()

    from ai.client import is_available, chat

    if is_available():
        try:
            items = []
            for aid in article_ids:
                a = articles_by_id.get(aid)
                if a:
                    items.append({
                        "id": aid,
                        "title": a.title[:100],
                        "category": a.category or "geral",
                        "score": round(a.score or 0, 2),
                        "source": a.source or "",
                    })

            system = (
                "Você é o editor-chefe de um telejornal brasileiro. "
                "Sua tarefa é definir a ordem ideal das notícias para uma edição do jornal. "
                "Critérios: (1) notícia mais importante/impactante primeiro, "
                "(2) nunca duas notícias da mesma categoria em sequência, "
                "(3) fluxo natural — misture temas para manter o telespectador engajado, "
                "(4) encerre com esportes ou notícia leve se houver. "
                "Responda APENAS com um array JSON dos IDs na nova ordem, sem explicação."
            )
            user = (
                f"Notícias disponíveis:\n{json.dumps(items, ensure_ascii=False, indent=2)}\n\n"
                f"Retorne APENAS o array JSON com os IDs na ordem ideal. Exemplo: [{article_ids[0]}, ...]"
            )

            raw = chat(system=system, user=user, max_tokens=300)
            match = re.search(r"\[[\d,\s]+\]", raw)
            if match:
                ordered = json.loads(match.group())
                # Valida: todos os IDs originais devem estar presentes
                orig_set = set(article_ids)
                ordered_valid = [aid for aid in ordered if aid in orig_set]
                # Adiciona IDs que a IA eventualmente omitiu
                missing = [aid for aid in article_ids if aid not in ordered_valid]
                result = ordered_valid + missing
                if len(result) == len(article_ids):
                    log(f"IA sequenciou {len(result)} notícias em ordem natural")
                    return result
        except Exception as e:
            logger.warning(f"Sequenciamento IA falhou, usando heurística: {e}")

    # Fallback heurístico: pontuação decrescente + alternância de categoria
    return _heuristic_sequence(article_ids, articles_by_id, log)


def _heuristic_sequence(
    article_ids: list[int],
    articles_by_id: dict,
    log: Callable,
) -> list[int]:
    """
    Ordena sem IA:
    - Ordena por score descendente
    - Reordena para evitar mesma categoria consecutiva (greedy)
    - Esportes vão para o final
    """
    SPORT_CATS = {"esporte"}
    LAST_CATS = {"esporte"}

    def sort_key(aid):
        a = articles_by_id.get(aid)
        if not a:
            return (1, 0)
        is_last = 1 if a.category in LAST_CATS else 0
        return (is_last, -(a.score or 0))

    sorted_ids = sorted(article_ids, key=sort_key)

    # Reordena para evitar categorias consecutivas (greedy)
    result = []
    remaining = list(sorted_ids)
    last_cat = None

    while remaining:
        # Tenta pegar o próximo de categoria diferente com maior score
        chosen = None
        for i, aid in enumerate(remaining):
            cat = (articles_by_id.get(aid) or type("", (), {"category": None})()).category
            if cat != last_cat or len(remaining) == 1:
                chosen = remaining.pop(i)
                last_cat = cat
                break
        if chosen is None:
            chosen = remaining.pop(0)
            last_cat = (articles_by_id.get(chosen) or type("", (), {"category": None})()).category
        result.append(chosen)

    log(f"Heurística sequenciou {len(result)} notícias")
    return result
