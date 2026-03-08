"""
=============================================================
  Web Crawler de Notícias com IA (Ollama - kimi-k2.5:cloud)
  Suporte a sites estáticos (requests) e dinâmicos (Playwright)
=============================================================

Instalação:
    pip install requests beautifulsoup4 ollama playwright
    playwright install chromium

Uso:
    python news_crawler.py
    python news_crawler.py --url https://g1.globo.com/alguma-noticia
    python news_crawler.py --file urls.txt
    python news_crawler.py --url https://site.com --js   (força modo JS)
"""

import argparse
import json
import sys
import time
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    import ollama
except ImportError:
    print("[ERRO] Instale o ollama: pip install ollama")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────
# CONFIGURAÇÕES
# ──────────────────────────────────────────────────────────────

OLLAMA_MODEL    = "kimi-k2.5:cloud"   # modelo Ollama a usar
REQUEST_TIMEOUT = 15                  # segundos para requests HTTP
DELAY_ENTRE_URLS = 1.5               # pausa entre crawls (respeita servidor)
MAX_CHARS_PARA_IA = 5000             # limite de texto enviado à IA
OUTPUT_FILE = "noticias_extraidas.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ──────────────────────────────────────────────────────────────
# DETECÇÃO AUTOMÁTICA: precisa de JS?
# ──────────────────────────────────────────────────────────────

JS_DOMAINS = [
    "bloomberg.com", "reuters.com", "wsj.com",
    "folha.uol.com.br", "estadao.com.br",
    "infomoney.com.br", "investing.com",
]

def precisa_js(url: str) -> bool:
    """Retorna True se o domínio normalmente requer JavaScript."""
    return any(d in url for d in JS_DOMAINS)


# ──────────────────────────────────────────────────────────────
# SCRAPING: modo estático (requests + BeautifulSoup)
# ──────────────────────────────────────────────────────────────

def fetch_estatico(url: str) -> str:
    """Busca HTML via requests simples. Rápido e leve."""
    print(f"  → [HTTP] buscando {url}")
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


# ──────────────────────────────────────────────────────────────
# SCRAPING: modo dinâmico (Playwright — suporta JavaScript)
# ──────────────────────────────────────────────────────────────

def fetch_dinamico(url: str) -> str:
    """Usa Playwright para renderizar JavaScript antes de extrair o HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERRO] Playwright não instalado: pip install playwright && playwright install chromium")
        sys.exit(1)

    print(f"  → [JS/Playwright] renderizando {url}")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # Bloqueia recursos pesados que não precisamos
        page.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,mp4,webm}",
            lambda route: route.abort()
        )

        page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Aguarda o conteúdo principal aparecer (tenta alguns seletores comuns)
        for seletor in ["article", "main", ".content", "#content", "h1"]:
            try:
                page.wait_for_selector(seletor, timeout=5_000)
                break
            except Exception:
                continue

        html = page.content()
        browser.close()

    return html


# ──────────────────────────────────────────────────────────────
# LIMPEZA DO HTML
# ──────────────────────────────────────────────────────────────

TAGS_REMOVER = [
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "iframe", "svg", "button", "figure",
    "advertisement", "ads", ".ad", ".banner",
]

def limpar_html(html: str) -> str:
    """Remove ruído do HTML e retorna texto limpo."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(TAGS_REMOVER):
        tag.decompose()

    # Remove atributos desnecessários
    for tag in soup.find_all(True):
        tag.attrs = {}

    texto = soup.get_text(separator="\n", strip=True)

    # Remove linhas muito curtas (menus, botões, etc.)
    linhas = [l.strip() for l in texto.splitlines() if len(l.strip()) > 30]
    texto = "\n".join(linhas)

    # Remove espaços múltiplos
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto[:MAX_CHARS_PARA_IA]


# ──────────────────────────────────────────────────────────────
# EXTRAÇÃO COM IA (Ollama - kimi-k2.5:cloud)
# ──────────────────────────────────────────────────────────────

PROMPT_SISTEMA = """Você é um assistente especializado em extração de informações de notícias.
Sempre responda APENAS com JSON válido, sem texto extra, sem markdown, sem blocos de código.
"""

PROMPT_EXTRACAO = """Extraia as seguintes informações da notícia abaixo e responda SOMENTE com JSON:

{{
  "titulo": "título completo da notícia",
  "autor": "nome do autor ou 'Não informado'",
  "data_publicacao": "data no formato DD/MM/AAAA ou 'Não informada'",
  "veiculo": "nome do portal/jornal ou 'Não identificado'",
  "categoria": "editoria/categoria (ex: Política, Economia, Tecnologia)",
  "resumo": "resumo objetivo em 3-4 frases",
  "topicos_principais": ["tópico 1", "tópico 2", "tópico 3"],
  "entidades_mencionadas": {{
    "pessoas": ["nome1", "nome2"],
    "organizacoes": ["org1", "org2"],
    "locais": ["local1", "local2"]
  }},
  "sentimento": "positivo | negativo | neutro",
  "palavras_chave": ["kw1", "kw2", "kw3", "kw4", "kw5"]
}}

--- NOTÍCIA ---
{texto}
--- FIM ---
"""

def extrair_com_ia(texto: str, url: str) -> dict:
    """Envia o texto para o Ollama e retorna os dados extraídos."""
    print(f"  → [IA] enviando para {OLLAMA_MODEL}...")

    prompt = PROMPT_EXTRACAO.format(texto=texto)

    try:
        resposta = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user",   "content": prompt},
            ],
            options={"temperature": 0.1},  # mais determinístico
        )
    except Exception as e:
        raise RuntimeError(f"Erro ao chamar Ollama: {e}") from e

    conteudo = resposta["message"]["content"].strip()

    # Remove possíveis blocos markdown que o modelo pode incluir
    conteudo = re.sub(r"^```(?:json)?", "", conteudo, flags=re.MULTILINE)
    conteudo = re.sub(r"```$", "", conteudo, flags=re.MULTILINE).strip()

    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError:
        # Tenta extrair o JSON de dentro da resposta
        match = re.search(r"\{.*\}", conteudo, re.DOTALL)
        if match:
            dados = json.loads(match.group())
        else:
            dados = {"erro_parse": conteudo}

    return dados


# ──────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL: URL → HTML → Texto → IA → JSON
# ──────────────────────────────────────────────────────────────

def crawl_noticia(url: str, forcar_js: bool = False) -> dict:
    """
    Pipeline completo para uma URL:
    1. Busca o HTML (estático ou via JS)
    2. Limpa e extrai o texto
    3. Envia à IA para estruturar os dados
    """
    resultado = {
        "url": url,
        "crawled_at": datetime.now().isoformat(),
        "modo": None,
        "dados": None,
        "erro": None,
    }

    try:
        # ── 1. FETCH ──────────────────────────────────────────
        usa_js = forcar_js or precisa_js(url)
        resultado["modo"] = "playwright_js" if usa_js else "requests_http"

        html = fetch_dinamico(url) if usa_js else fetch_estatico(url)

        # ── 2. LIMPEZA ────────────────────────────────────────
        texto = limpar_html(html)
        if len(texto) < 200:
            raise ValueError(f"Texto muito curto ({len(texto)} chars) — página pode exigir login ou JS")

        print(f"  → Texto extraído: {len(texto)} caracteres")

        # ── 3. IA ────────────────────────────────────────────
        resultado["dados"] = extrair_com_ia(texto, url)
        print(f"  → ✅ Extração concluída!")

    except Exception as e:
        resultado["erro"] = str(e)
        print(f"  → ❌ Erro: {e}")

    return resultado


def crawl_multiplas(urls: list[str], forcar_js: bool = False) -> list[dict]:
    """Processa uma lista de URLs com pausa entre cada uma."""
    resultados = []
    total = len(urls)

    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{total}] {url}")
        resultado = crawl_noticia(url, forcar_js=forcar_js)
        resultados.append(resultado)

        if i < total:
            print(f"  → aguardando {DELAY_ENTRE_URLS}s...")
            time.sleep(DELAY_ENTRE_URLS)

    return resultados


# ──────────────────────────────────────────────────────────────
# SAÍDA
# ──────────────────────────────────────────────────────────────

def salvar_json(resultados: list[dict], caminho: str):
    Path(caminho).write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n💾 Resultados salvos em: {caminho}")


def imprimir_resumo(resultados: list[dict]):
    print("\n" + "═" * 60)
    print("  RESUMO DA EXTRAÇÃO")
    print("═" * 60)
    for r in resultados:
        status = "✅" if not r["erro"] else "❌"
        print(f"\n{status} {r['url']}")
        if r["dados"] and not r["erro"]:
            d = r["dados"]
            print(f"   Título    : {d.get('titulo', '—')}")
            print(f"   Autor     : {d.get('autor', '—')}")
            print(f"   Data      : {d.get('data_publicacao', '—')}")
            print(f"   Sentimento: {d.get('sentimento', '—')}")
            print(f"   Resumo    : {d.get('resumo', '—')[:120]}...")
        elif r["erro"]:
            print(f"   Erro      : {r['erro']}")
    print("\n" + "═" * 60)


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

URLS_EXEMPLO = [
    "https://g1.globo.com/tecnologia/",
    "https://www.bbc.com/portuguese/articles/c0j99gl8dvgo",
]

def main():
    parser = argparse.ArgumentParser(
        description="Web Crawler de Notícias com IA (Ollama kimi-k2.5:cloud)"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url",  help="URL única para crawlear")
    group.add_argument("--file", help="Arquivo .txt com uma URL por linha")
    parser.add_argument("--js",  action="store_true", help="Força uso do Playwright (JS)")
    parser.add_argument("--out", default=OUTPUT_FILE, help=f"Arquivo de saída JSON (padrão: {OUTPUT_FILE})")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════╗")
    print("║  News Crawler  ·  Ollama kimi-k2.5:cloud     ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"Modelo : {OLLAMA_MODEL}")
    print(f"Saída  : {args.out}\n")

    # Determina lista de URLs
    if args.url:
        urls = [args.url]
    elif args.file:
        urls = Path(args.file).read_text(encoding="utf-8").splitlines()
        urls = [u.strip() for u in urls if u.strip() and not u.startswith("#")]
    else:
        print("Nenhuma URL fornecida — usando URLs de exemplo:\n")
        for u in URLS_EXEMPLO:
            print(f"  • {u}")
        urls = URLS_EXEMPLO

    # Executa o crawler
    resultados = crawl_multiplas(urls, forcar_js=args.js)

    # Exibe e salva
    imprimir_resumo(resultados)
    salvar_json(resultados, args.out)


if __name__ == "__main__":
    main()
