"""
Efeitos visuais animados para o canal Brasil24.
- Fundo genérico animado (gradiente + partículas) quando não há imagem
- Efeito Ken Burns (zoom lento) quando há imagem
- Overlays animados: ticker, entidades, sentimento, persona label
"""
import math
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

W, H = 1920, 1080
FPS = 24

# Fontes
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

# ── Cores por categoria ──────────────────────────────────────────────────────
CATEGORY_PALETTE = {
    "politica": {"dark": (18, 8, 28),  "mid": (55, 15, 75),  "accent": (192, 57, 43)},
    "economia": {"dark": (8, 22, 12),  "mid": (15, 60, 35),  "accent": (39, 174, 96)},
    "saude":    {"dark": (18, 8, 28),  "mid": (45, 12, 70),  "accent": (142, 68, 173)},
    "tech":     {"dark": (8, 18, 28),  "mid": (8, 45, 75),   "accent": (22, 160, 133)},
    "esporte":  {"dark": (28, 12, 4),  "mid": (75, 35, 8),   "accent": (230, 126, 34)},
    "geral":    {"dark": (8, 12, 22),  "mid": (18, 28, 55),  "accent": (41, 128, 185)},
}

SENTIMENT_COLORS = {
    "positivo": (39, 174, 96),
    "negativo": (231, 76, 60),
    "neutro":   (52, 152, 219),
}

PERSONA_COLORS = {
    "ana":    (232, 168, 56),
    "carlos": (74, 144, 217),
    "guest":  (39, 174, 96),
}

PERSONA_NAMES = {
    "ana":    "Ana Silva",
    "carlos": "Carlos Mendes",
    "guest":  "Convidado",
}


# ── Fundo genérico animado ───────────────────────────────────────────────────

def make_generic_bg(t: float, category: str, sentiment: str) -> np.ndarray:
    """
    Gera fundo animado com gradiente + grid + linhas diagonais em movimento.
    t = tempo em segundos.
    """
    palette = CATEGORY_PALETTE.get(category, CATEGORY_PALETTE["geral"])
    dark, mid = palette["dark"], palette["mid"]
    accent = SENTIMENT_COLORS.get(sentiment, SENTIMENT_COLORS["neutro"])

    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Gradiente vertical dark → mid
    for y in range(H):
        ratio = y / H
        r = int(dark[0] + (mid[0] - dark[0]) * ratio)
        g = int(dark[1] + (mid[1] - dark[1]) * ratio)
        b = int(dark[2] + (mid[2] - dark[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Linhas diagonais que se movem lentamente
    speed = 20
    offset = int(t * speed) % 160
    for x in range(-H, W + H, 160):
        x0 = x + offset
        draw.line([(x0, 0), (x0 + H, H)], fill=(*accent, 12), width=2)

    # Grid sutil
    for x in range(0, W, 120):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255), width=1)
    for y in range(0, H, 120):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255), width=1)

    # Vinheta (escurecer bordas)
    vignette = Image.new("RGB", (W, H), (0, 0, 0))
    arr_v = np.array(vignette, dtype=float)
    arr_i = np.array(img, dtype=float)
    for y in range(H):
        for_x = np.arange(W)
        dist_y = min(y, H - y) / (H * 0.4)
        dist_x = np.minimum(for_x, W - for_x) / (W * 0.4)
        alpha = np.clip(np.minimum(dist_x, dist_y), 0, 1)
        arr_i[y] = arr_i[y] * alpha[:, None] + arr_v[y] * (1 - alpha[:, None])

    # Pulso central animado (circulo de luz suave)
    pulse = (math.sin(t * 0.5) + 1) / 2  # 0..1 lento
    cx, cy = W // 2, H // 2
    radius = int(300 + pulse * 80)
    for r_off in range(radius, 0, -20):
        alpha_val = int(6 * (1 - r_off / radius))
        color_pulse = tuple(min(255, c + 30) for c in palette["accent"]) if hasattr(palette, "accent") else accent
        draw2 = ImageDraw.Draw(img)
        draw2.ellipse(
            [(cx - r_off, cy - r_off), (cx + r_off, cy + r_off)],
            outline=(*accent, alpha_val),
            width=2,
        )

    # Sobreposição escura para garantir leitura do texto
    overlay = Image.new("RGB", (W, H), (0, 0, 0))
    img = Image.blend(Image.fromarray(arr_i.astype(np.uint8)), overlay, 0.35)

    return np.array(img)


# ── Ken Burns em imagem real ─────────────────────────────────────────────────

def apply_ken_burns(image_array: np.ndarray, t: float, duration: float) -> np.ndarray:
    """
    Aplica zoom lento (Ken Burns effect) em uma imagem.
    Vai de zoom 1.0 para 1.08 ao longo da duração.
    """
    progress = min(t / max(duration, 1), 1.0)
    zoom = 1.0 + 0.08 * progress
    pan_x = int(30 * progress)   # pan levíssimo para a direita
    pan_y = int(15 * progress)   # e levíssimo para baixo

    img = Image.fromarray(image_array)
    new_w = int(W * zoom)
    new_h = int(H * zoom)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Crop central com pan
    left = (new_w - W) // 2 + pan_x
    top  = (new_h - H) // 2 + pan_y
    left = max(0, min(left, new_w - W))
    top  = max(0, min(top, new_h - H))
    img = img.crop((left, top, left + W, top + H))
    return np.array(img)


def prepare_image_bg(image_path: Path) -> Optional[np.ndarray]:
    """Prepara a imagem de fundo (blur + escurecer) uma única vez."""
    try:
        img = Image.open(image_path).convert("RGB")
        img = img.resize((W, H), Image.LANCZOS)
        img = img.filter(ImageFilter.GaussianBlur(radius=8))
        overlay = Image.new("RGB", (W, H), (0, 0, 0))
        img = Image.blend(img, overlay, 0.45)
        return np.array(img)
    except Exception as e:
        logger.warning(f"Falha ao preparar imagem: {e}")
        return None


# ── Overlays de texto ────────────────────────────────────────────────────────

def draw_frame_overlays(
    bg: np.ndarray,
    t: float,
    seg_start: float,
    title: str,
    persona: str,
    entities: list[str],
    sentiment: str,
    category: str,
    ticker_text: str,
    seg_index: int,
    total_segs: int,
) -> np.ndarray:
    """
    Desenha todos os overlays sobre o frame de fundo.
    Inclui: logo, título, label do personagem, barra de sentimento,
    overlay de entidade rotativo, ticker animado.
    """
    img = Image.fromarray(bg.copy()).convert("RGBA")
    overlay_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_layer)

    # Tempo local neste segmento (para animações de slide)
    local_t = t - seg_start
    slide_in = min(local_t / 0.4, 1.0)  # 0→1 em 0.4s (slide de entrada)

    # ── Gradiente inferior (fundo para texto) ──────────────────────────────
    grad_h = 260
    for i in range(grad_h):
        alpha = int(210 * (i / grad_h) ** 1.5)
        draw.rectangle(
            [(0, H - grad_h + i), (W, H - grad_h + i + 1)],
            fill=(0, 0, 0, alpha),
        )

    # ── Título ────────────────────────────────────────────────────────────
    font_title = _font(FONT_BOLD, 52)
    font_sub   = _font(FONT_REG,  30)
    font_persona = _font(FONT_BOLD, 32)
    font_ticker  = _font(FONT_BOLD, 26)
    font_logo    = _font(FONT_BOLD, 38)
    font_entity  = _font(FONT_REG, 26)

    # Quebra o título em linhas
    words = title.split()
    lines, line = [], []
    for w in words:
        test = " ".join(line + [w])
        bbox = draw.textbbox((0, 0), test, font=font_title)
        if bbox[2] > W - 120:
            if line:
                lines.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))

    y_title = H - 190
    for line_text in lines[:3]:
        draw.text((60, y_title), line_text, font=font_title, fill=(240, 242, 247, 255))
        y_title += 62

    # ── Label do personagem (slide from left) ─────────────────────────────
    persona_color = PERSONA_COLORS.get(persona, (232, 168, 56))
    persona_name  = PERSONA_NAMES.get(persona, "Apresentador")

    label_w = len(persona_name) * 19 + 28
    label_x = int(-label_w + label_w * slide_in) + 60  # slide da esquerda
    draw.rectangle(
        [(label_x, H - 260), (label_x + label_w, H - 228)],
        fill=(*persona_color, 240),
    )
    draw.text((label_x + 10, H - 257), persona_name, font=font_persona, fill=(255, 255, 255, 255))

    # ── Barra de sentimento (canto inferior direito) ───────────────────────
    sent_color = SENTIMENT_COLORS.get(sentiment, (52, 152, 219))
    sent_label = {"positivo": "POSITIVO", "negativo": "NEGATIVO", "neutro": "NEUTRO"}.get(sentiment, "NEUTRO")
    bar_w = 200
    draw.rectangle(
        [(W - bar_w - 20, H - 265), (W - 20, H - 235)],
        fill=(*sent_color, 200),
    )
    draw.text((W - bar_w - 8, H - 260), sent_label, font=_font(FONT_BOLD, 22), fill=(255, 255, 255, 255))

    # ── Overlay de entidade rotativa (aparece a cada 4s) ──────────────────
    if entities:
        entity_idx = int(t / 4) % len(entities)
        entity_text = entities[entity_idx]
        # Aparece por 3s, desaparece 1s
        entity_phase = (t % 4)
        if entity_phase < 3.0:
            entity_alpha = min(entity_phase / 0.3, 1.0, (3.0 - entity_phase) / 0.3)
            entity_alpha = int(entity_alpha * 220)
            ew = len(entity_text) * 16 + 24
            draw.rectangle(
                [(60, H - 310), (60 + ew, H - 282)],
                fill=(0, 0, 0, entity_alpha),
            )
            draw.text((70, H - 308), entity_text, font=font_entity, fill=(180, 220, 255, entity_alpha))

    # ── Ticker animado ────────────────────────────────────────────────────
    ticker_h = 44
    draw.rectangle([(0, H - ticker_h), (W, H)], fill=(10, 12, 18, 245))
    draw.rectangle([(0, H - ticker_h), (8, H)], fill=(232, 51, 42, 255))

    # Desloca o texto do ticker com o tempo
    # Unidade de loop: texto uma única vez com separadores
    ticker_unit = f"   ●   {ticker_text}   ●   BRASIL24 — NOTICIAS AO VIVO   "
    # Mede a largura real da unidade de loop
    if hasattr(draw, "textlength"):
        loop_w = int(draw.textlength(ticker_unit, font=font_ticker))
    else:
        bbox = draw.textbbox((0, 0), ticker_unit, font=font_ticker)
        loop_w = bbox[2] - bbox[0]
    loop_w = max(loop_w, W + 1)  # garante que a unidade é pelo menos 1px mais larga que a tela
    speed_px = 80  # pixels/s
    offset_px = int(t * speed_px) % loop_w
    x1 = 20 - offset_px
    # Desenha a unidade de loop duas vezes sem sobreposição: cópia 1 e cópia 2 logo após
    draw.text((x1,          H - ticker_h + 8), ticker_unit, font=font_ticker, fill=(200, 210, 230, 255))
    draw.text((x1 + loop_w, H - ticker_h + 8), ticker_unit, font=font_ticker, fill=(200, 210, 230, 255))

    # ── Logo BRASIL24 ──────────────────────────────────────────────────────
    logo_x, logo_y = W - 210, 16
    draw.rectangle([(logo_x - 8, logo_y - 4), (W - 12, logo_y + 50)], fill=(10, 12, 18, 220))
    draw.text((logo_x, logo_y), "BRASIL", font=font_logo, fill=(240, 242, 247, 255))
    # "24" em cor de destaque
    b_w = int(draw.textlength("BRASIL", font=font_logo)) if hasattr(draw, "textlength") else 130
    draw.text((logo_x + b_w, logo_y), "24", font=font_logo, fill=(232, 168, 56, 255))

    # ── Badge AO VIVO (pisca) ──────────────────────────────────────────────
    if int(t * 2) % 2 == 0:  # pisca 0.5Hz
        draw.ellipse([(logo_x - 22, logo_y + 10), (logo_x - 8, logo_y + 24)], fill=(232, 51, 42, 255))

    # Composita overlay sobre fundo
    img = Image.alpha_composite(img, overlay_layer)
    return np.array(img.convert("RGB"))


# ── Utilitário: lista de entidades para overlay ──────────────────────────────

def build_entity_list(enrichment: Optional[dict]) -> list[str]:
    """Retorna lista plana de entidades para o overlay rotativo."""
    if not enrichment:
        return []
    ents = enrichment.get("entidades_mencionadas", {})
    if not isinstance(ents, dict):
        return []
    items = []
    for pessoa in ents.get("pessoas", [])[:3]:
        items.append(f"👤 {pessoa}")
    for org in ents.get("organizacoes", [])[:3]:
        items.append(f"🏛 {org}")
    for local in ents.get("locais", [])[:2]:
        items.append(f"📍 {local}")
    return items
