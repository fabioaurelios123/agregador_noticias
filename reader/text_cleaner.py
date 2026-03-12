"""
Prepara o texto do artigo para leitura em TTS.
Remove HTML, URLs, caracteres especiais e formata para leitura natural.
Sem IA — processamento puramente textual.
"""
import re
import unicodedata


# Limite de caracteres por chunk (edge-tts tem limite de ~3000 chars por chamada)
CHUNK_MAX_CHARS = 2500


def _strip_html(text: str) -> str:
    """Remove tags HTML."""
    return re.sub(r"<[^>]+>", " ", text)


def _strip_urls(text: str) -> str:
    """Remove URLs."""
    return re.sub(r"https?://\S+", "", text)


def _normalize_whitespace(text: str) -> str:
    """Colapsa múltiplos espaços/quebras em um único espaço."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_junk(text: str) -> str:
    """Remove caracteres de controle e símbolos desnecessários."""
    # Mantém letras, números, pontuação básica e acentos
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch)[0] in ("L", "N", "Z", "P")
        or ch in "\n"
    )
    return text


def clean_for_tts(text: str) -> str:
    """Pipeline completo de limpeza de texto para TTS."""
    text = _strip_html(text)
    text = _strip_urls(text)
    text = _remove_junk(text)
    text = _normalize_whitespace(text)
    return text


def build_reading_text(title: str, content: str, source: str) -> str:
    """
    Constrói o texto completo de leitura para um artigo.
    Formato: cabeçalho → conteúdo limpo.
    """
    header = f"Notícia: {title.strip()}. Fonte: {source.strip()}."
    body = clean_for_tts(content) if content else ""

    if body:
        return f"{header}\n\n{body}"
    return header


def split_into_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """
    Divide o texto em chunks respeitando frases completas.
    Necessário pois TTS tem limite por chamada.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    # Divide por parágrafo primeiro
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    current = ""
    for para in paragraphs:
        # Parágrafo maior que o limite → divide por frases
        if len(para) > max_chars:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars:
                    current = f"{current} {sentence}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sentence
        else:
            if len(current) + len(para) + 2 <= max_chars:
                current = f"{current}\n\n{para}".strip() if current else para
            else:
                if current:
                    chunks.append(current)
                current = para

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_chars]]
