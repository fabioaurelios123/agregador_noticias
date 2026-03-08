"""
Enriquece uma notícia via URL usando o mesmo pipeline do python_summary_news_test.py.
Extrai: titulo, autor, data, sentimento, topicos, entidades, palavras_chave.
Usa ai/client.py (Anthropic ou Ollama) conforme AI_PROVIDER.
"""
import json
import logging
import re
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config.settings import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_CHARS = 5000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Domínios que normalmente requerem JS
JS_DOMAINS = [
    "bloomberg.com", "reuters.com", "wsj.com",
    "folha.uol.com.br", "estadao.com.br",
    "infomoney.com.br", "investing.com",
]

TAGS_REMOVER = [
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "iframe", "svg", "button", "figure",
]

ENRICH_SYSTEM = """Você é um assistente especializado em extração de informações de notícias brasileiras.
Sempre responda APENAS com JSON válido, sem texto extra, sem markdown, sem blocos de código."""

ENRICH_PROMPT = """Extraia as informações da notícia abaixo e responda SOMENTE com JSON:

{{
  "titulo": "título completo da notícia",
  "autor": "nome do autor ou 'Não informado'",
  "data_publicacao": "data no formato DD/MM/AAAA ou 'Não informada'",
  "veiculo": "nome do portal/jornal",
  "categoria": "editoria (Política, Economia, Saúde, Tecnologia, Esporte, Geral)",
  "resumo": "resumo objetivo em 3-4 frases",
  "topicos_principais": ["tópico 1", "tópico 2", "tópico 3"],
  "entidades_mencionadas": {{
    "pessoas": ["nome1", "nome2"],
    "organizacoes": ["org1", "org2"],
    "locais": ["local1", "local2"]
  }},
  "sentimento": "positivo | negativo | neutro",
  "impacto": "alto | medio | baixo",
  "palavras_chave": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "angulo_discussao": "aspecto mais controverso ou interessante para debate no podcast"
}}

--- NOTÍCIA ---
{texto}
--- FIM ---
"""


def _fetch_html(url: str, force_js: bool = False) -> Optional[str]:
    """Busca o HTML da URL via requests ou Playwright."""
    needs_js = force_js or any(d in url for d in JS_DOMAINS)

    if needs_js:
        return _fetch_playwright(url)
    return _fetch_static(url)


def _fetch_static(url: str) -> Optional[str]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"Static fetch failed for {url}: {e}")
        return None


def _fetch_playwright(url: str) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright não instalado — usando fetch estático")
        return _fetch_static(url)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=HEADERS["User-Agent"])
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,mp4,webm}",
                       lambda route: route.abort())
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            for sel in ["article", "main", ".content", "#content", "h1"]:
                try:
                    page.wait_for_selector(sel, timeout=4_000)
                    break
                except Exception:
                    continue
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        logger.warning(f"Playwright fetch failed: {e}")
        return None


def _extract_image_from_html(html: str) -> Optional[str]:
    """Tenta extrair a imagem principal da notícia do HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # og:image meta tag (mais confiável)
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]

    # twitter:image
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return tw["content"]

    # Primeira imagem grande dentro de article/figure
    for tag in soup.select("article img, figure img, .article img"):
        src = tag.get("src") or tag.get("data-src")
        if src and src.startswith("http") and any(ext in src.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return src

    return None


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(TAGS_REMOVER):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 30]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_CHARS]


def enrich_url(url: str, force_js: bool = False) -> Optional[dict]:
    """
    Pipeline completo: URL → HTML → texto → IA → dados estruturados.

    Retorna dict com campos:
        titulo, autor, data_publicacao, veiculo, categoria, resumo,
        topicos_principais, entidades_mencionadas, sentimento, impacto,
        palavras_chave, angulo_discussao, image_url
    Ou None em caso de falha.
    """
    from ai.client import chat, is_available

    logger.info(f"Enriching URL: {url}")

    html = _fetch_html(url, force_js)
    if not html:
        logger.warning(f"Could not fetch HTML for {url}")
        return None

    # Extrair imagem antes de limpar o HTML
    image_url = _extract_image_from_html(html)

    text = _clean_text(html)
    if len(text) < 200:
        logger.warning(f"Text too short ({len(text)} chars) for {url}")
        return None

    logger.info(f"Text extracted: {len(text)} chars. Sending to AI...")

    if not is_available():
        logger.warning("AI not available — skipping enrichment")
        return None

    prompt = ENRICH_PROMPT.format(texto=text)

    try:
        raw = chat(system=ENRICH_SYSTEM, user=prompt, max_tokens=800)
    except Exception as e:
        logger.error(f"AI enrichment call failed: {e}")
        return None

    # Limpa possível markdown
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error("Could not parse AI enrichment JSON")
                return None
        else:
            logger.error("No JSON found in AI enrichment response")
            return None

    data["image_url"] = image_url
    data["source_url"] = url
    logger.info(f"Enrichment complete: sentimento={data.get('sentimento')} impacto={data.get('impacto')}")
    return data


def enrich_article_by_id(article_id: int) -> Optional[dict]:
    """Enriquece o artigo do banco pelo ID."""
    from database.db import get_session_factory
    from database.models import Article

    db = get_session_factory()()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return None
        return enrich_url(article.url)
    finally:
        db.close()
