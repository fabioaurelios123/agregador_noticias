"""
Gera diálogos estilo podcast entre os personagens de notícias,
usando o provedor AI configurado (Anthropic Claude ou Ollama).
Suporta dados de enriquecimento para diálogos mais ricos e contextuais.
"""
import json
import logging
import re
from typing import Optional

from config.settings import settings
from ai.prompts import (
    DIALOGUE_SYSTEM,
    DIALOGUE_USER,
    ANA_STYLE,
    CARLOS_STYLE,
    CATEGORY_GUEST_MAP,
    ENRICHMENT_DEFAULTS,
)

logger = logging.getLogger(__name__)


def _fallback_dialogue(title: str, summary: str, category: str, enrichment: dict) -> list[dict]:
    """Diálogo padrão quando nenhum provedor AI está disponível."""
    guest = CATEGORY_GUEST_MAP.get(category, CATEGORY_GUEST_MAP["geral"])
    pessoas = enrichment.get("entidades_mencionadas", {}).get("pessoas", [])
    entidade_str = f", especialmente envolvendo {', '.join(pessoas[:2])}" if pessoas else ""

    return [
        {"persona": "ana", "text": f"Boa tarde. Acompanhe agora: {title}.", "emotion": "neutro"},
        {"persona": "carlos", "text": f"Exatamente, Ana. Esta notícia{entidade_str} merece atenção.", "emotion": "analitico"},
        {"persona": "guest", "text": f"Como {guest['role']}, posso dizer que o impacto é {enrichment.get('impacto', 'relevante')} para o Brasil.", "emotion": "especialista"},
        {"persona": "ana", "text": summary[:200] if summary else "Acompanhe mais detalhes em nosso portal.", "emotion": "neutro"},
        {"persona": "carlos", "text": "É fundamental que a população fique atenta a esses desenvolvimentos.", "emotion": "analitico"},
        {"persona": "ana", "text": "Continuamos acompanhando. Fique ligado no Brasil24.", "emotion": "neutro"},
    ]


def _parse_script(raw: str, title: str, summary: str, category: str, enrichment: dict) -> list[dict]:
    """Extrai e valida o JSON do script retornado pela IA."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("IA não retornou JSON array válido — usando fallback")
        return _fallback_dialogue(title, summary, category, enrichment)
    try:
        script = json.loads(match.group())
        if isinstance(script, list) and all("persona" in s and "text" in s for s in script):
            return script
    except json.JSONDecodeError:
        pass
    logger.warning("Falha ao parsear JSON da IA — usando fallback")
    return _fallback_dialogue(title, summary, category, enrichment)


def generate_dialogue(
    title: str,
    summary: str,
    category: str = "geral",
    enrichment: Optional[dict] = None,
) -> list[dict]:
    """
    Gera script de diálogo estilo podcast.
    Retorna lista de {persona, text, emotion}.

    enrichment: dict opcional com dados do enricher (sentimento, entidades, etc.)
    """
    from ai.client import chat, is_available

    # Mescla defaults com dados reais do enrichment
    ctx = {**ENRICHMENT_DEFAULTS, **(enrichment or {})}
    entidades = ctx.get("entidades_mencionadas", {})
    if not isinstance(entidades, dict):
        entidades = {}

    if not is_available():
        logger.warning(f"Provedor AI '{settings.ai_provider}' indisponível — usando fallback")
        return _fallback_dialogue(title, summary, category, ctx)

    guest = CATEGORY_GUEST_MAP.get(category, CATEGORY_GUEST_MAP["geral"])

    prompt = DIALOGUE_USER.format(
        ana_style=ANA_STYLE,
        carlos_style=CARLOS_STYLE,
        guest_name=guest["name"],
        guest_role=guest["role"],
        guest_style=guest["style"],
        title=title,
        category=category,
        summary=summary[:1000],
        # Campos de enriquecimento
        sentimento=ctx.get("sentimento", "neutro"),
        impacto=ctx.get("impacto", "medio"),
        topicos=", ".join(ctx.get("topicos_principais", [])[:5]) or "não identificados",
        pessoas=", ".join(entidades.get("pessoas", [])[:4]) or "não identificadas",
        organizacoes=", ".join(entidades.get("organizacoes", [])[:4]) or "não identificadas",
        locais=", ".join(entidades.get("locais", [])[:3]) or "não identificados",
        palavras_chave=", ".join(ctx.get("palavras_chave", [])[:6]) or "não identificadas",
        angulo_discussao=ctx.get("angulo_discussao", "contexto geral da notícia"),
        autor=ctx.get("autor", "Não informado"),
        data_publicacao=ctx.get("data_publicacao", "Não informada"),
    )

    try:
        raw = chat(system=DIALOGUE_SYSTEM, user=prompt, max_tokens=1500)
        return _parse_script(raw, title, summary, category, ctx)
    except Exception as e:
        logger.error(f"Geração de diálogo falhou ({settings.ai_provider}): {e}")
        return _fallback_dialogue(title, summary, category, ctx)


def generate_dialogue_for_article(article_id: int) -> Optional[list[dict]]:
    """Carrega artigo do banco e gera diálogo."""
    from database.db import get_session_factory
    from database.models import Article

    db = get_session_factory()()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return None
        summary = article.summary or (article.content[:500] if article.content else article.title)
        return generate_dialogue(article.title, summary, article.category or "geral")
    finally:
        db.close()
