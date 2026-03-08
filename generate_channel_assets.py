"""
Gera o pacote completo de assets visuais para o canal Brasil24 no YouTube:
  - banner_youtube.png    (2048x1152 — banner do canal)
  - profile_picture.png   (500x500  — foto de perfil)
  - channel_info.txt      (nome, handle, descrição, tags)

Uso:
    venv/bin/python generate_channel_assets.py
Saída em: channel_assets/
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT_DIR = Path("channel_assets")
OUT_DIR.mkdir(exist_ok=True)

# ── Fontes ────────────────────────────────────────────────────────────────────

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()

# ── Paleta Brasil24 ───────────────────────────────────────────────────────────

BG_DARK    = (8, 10, 18)       # azul quase preto
BG_MID     = (14, 20, 40)      # azul escuro
ACCENT_RED = (220, 38, 38)     # vermelho
GOLD       = (232, 168, 56)    # dourado "24"
WHITE      = (240, 242, 250)
BLUE_LIGHT = (96, 165, 250)    # azul claro para detalhes
GRAY       = (120, 130, 150)


# ══════════════════════════════════════════════════════════════════════════════
# BANNER  2048 × 1152
# ══════════════════════════════════════════════════════════════════════════════

def make_banner() -> Path:
    W, H = 2048, 1152
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    # ── Gradiente de fundo ────────────────────────────────────────────────────
    for y in range(H):
        ratio = y / H
        r = int(BG_DARK[0] + (BG_MID[0] - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (BG_MID[1] - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (BG_MID[2] - BG_DARK[2]) * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # ── Grid de linhas sutis ──────────────────────────────────────────────────
    for x in range(0, W, 80):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 8), width=1)
    for y in range(0, H, 80):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, 8), width=1)

    # ── Linhas diagonais decorativas ──────────────────────────────────────────
    for x in range(-H, W + H, 200):
        draw.line([(x, 0), (x + H, H)], fill=(*BLUE_LIGHT, 15), width=1)

    # ── Círculo de luz central (glow) ─────────────────────────────────────────
    cx, cy = W // 2, H // 2
    for radius in range(500, 0, -20):
        alpha = int(18 * (1 - radius / 500))
        draw.ellipse(
            [(cx - radius, cy - radius), (cx + radius, cy + radius)],
            outline=(*BLUE_LIGHT, alpha),
            width=1,
        )

    # ── Faixa lateral esquerda (acento vermelho) ───────────────────────────────
    draw.rectangle([(0, 0), (12, H)], fill=ACCENT_RED)

    # ── Faixa inferior ─────────────────────────────────────────────────────────
    draw.rectangle([(0, H - 80), (W, H)], fill=(6, 8, 16))
    draw.rectangle([(0, H - 80), (W, H - 77)], fill=ACCENT_RED)

    # ── Logo principal: BRASIL + 24 ───────────────────────────────────────────
    f_brand  = font(FONT_BOLD, 220)
    f_num    = font(FONT_BOLD, 220)
    f_tag    = font(FONT_BOLD, 52)
    f_sub    = font(FONT_REG,  42)
    f_badge  = font(FONT_BOLD, 28)

    brand_text = "BRASIL"
    brand_w = int(draw.textlength(brand_text, font=f_brand)) if hasattr(draw, "textlength") else 700
    num_w   = int(draw.textlength("24", font=f_num)) if hasattr(draw, "textlength") else 270

    total_w = brand_w + num_w + 16
    x_start = (W - total_w) // 2
    y_logo  = H // 2 - 160

    # Sombra suave
    for off in range(8, 0, -2):
        shadow_alpha = 60 - off * 6
        draw.text(
            (x_start + off, y_logo + off),
            brand_text,
            font=f_brand,
            fill=(0, 0, 0),
        )

    draw.text((x_start, y_logo), brand_text, font=f_brand, fill=WHITE)
    draw.text((x_start + brand_w + 8, y_logo), "24", font=f_num, fill=GOLD)

    # ── Linha separadora sob o logo ───────────────────────────────────────────
    sep_y = y_logo + 230
    draw.rectangle([(x_start, sep_y), (x_start + total_w, sep_y + 3)], fill=ACCENT_RED)

    # ── Tagline ───────────────────────────────────────────────────────────────
    tag = "NOTÍCIAS DO BRASIL EM TEMPO REAL"
    tag_w = int(draw.textlength(tag, font=f_tag)) if hasattr(draw, "textlength") else 800
    draw.text(((W - tag_w) // 2, sep_y + 20), tag, font=f_tag, fill=GRAY)

    # ── Badges de categorias ──────────────────────────────────────────────────
    badges = ["POLÍTICA", "ECONOMIA", "TECNOLOGIA", "SAÚDE", "ESPORTE"]
    badge_colors = [
        (139, 92, 246),   # roxo — política
        (34, 197, 94),    # verde — economia
        (20, 184, 166),   # teal — tech
        (168, 85, 247),   # lilás — saúde
        (249, 115, 22),   # laranja — esporte
    ]
    badge_y = sep_y + 100
    badge_total = sum(
        int(draw.textlength(b, font=font(FONT_BOLD, 24))) + 36
        if hasattr(draw, "textlength") else 120
        for b in badges
    ) + (len(badges) - 1) * 16

    bx = (W - badge_total) // 2
    for badge, color in zip(badges, badge_colors):
        bw = int(draw.textlength(badge, font=font(FONT_BOLD, 24))) + 36 if hasattr(draw, "textlength") else 120
        draw.rounded_rectangle([(bx, badge_y), (bx + bw, badge_y + 40)], radius=20, fill=(*color, 220))
        tw = int(draw.textlength(badge, font=font(FONT_BOLD, 24))) if hasattr(draw, "textlength") else bw - 36
        draw.text((bx + (bw - tw) // 2, badge_y + 8), badge, font=font(FONT_BOLD, 24), fill=WHITE)
        bx += bw + 16

    # ── Texto "24 HORAS POR DIA" no rodapé ───────────────────────────────────
    footer = "📡  TRANSMISSÃO AO VIVO  ·  24 HORAS POR DIA  ·  7 DIAS POR SEMANA"
    fw = int(draw.textlength(footer, font=f_sub)) if hasattr(draw, "textlength") else 900
    draw.text(((W - fw) // 2, H - 62), footer, font=f_sub, fill=(*GRAY, 200))

    # ── Vinheta nas bordas ────────────────────────────────────────────────────
    arr = np.array(img, dtype=float)
    for y in range(H):
        for_x = np.arange(W)
        dist_y = min(y, H - y) / (H * 0.25)
        dist_x = np.minimum(for_x, W - for_x) / (W * 0.25)
        alpha = np.clip(np.minimum(dist_x, dist_y), 0, 1)
        arr[y] = arr[y] * alpha[:, None]

    img = Image.fromarray(arr.astype(np.uint8))

    # Redesenha elementos centrais sobre a vinheta (para não escurecer o logo)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (12, H)], fill=ACCENT_RED)
    draw.rectangle([(0, H - 80), (W, H)], fill=(6, 8, 16))
    draw.rectangle([(0, H - 80), (W, H - 77)], fill=ACCENT_RED)
    draw.text((x_start, y_logo), brand_text, font=f_brand, fill=WHITE)
    draw.text((x_start + brand_w + 8, y_logo), "24", font=f_num, fill=GOLD)
    draw.rectangle([(x_start, sep_y), (x_start + total_w, sep_y + 3)], fill=ACCENT_RED)
    draw.text(((W - tag_w) // 2, sep_y + 20), tag, font=f_tag, fill=GRAY)

    bx = (W - badge_total) // 2
    for badge, color in zip(badges, badge_colors):
        bw = int(draw.textlength(badge, font=font(FONT_BOLD, 24))) + 36 if hasattr(draw, "textlength") else 120
        draw.rounded_rectangle([(bx, badge_y), (bx + bw, badge_y + 40)], radius=20, fill=(*color, 220))
        tw = int(draw.textlength(badge, font=font(FONT_BOLD, 24))) if hasattr(draw, "textlength") else bw - 36
        draw.text((bx + (bw - tw) // 2, badge_y + 8), badge, font=font(FONT_BOLD, 24), fill=WHITE)
        bx += bw + 16

    draw.text(((W - fw) // 2, H - 62), footer, font=f_sub, fill=(*GRAY, 200))

    out = OUT_DIR / "banner_youtube.png"
    img.save(out, "PNG", optimize=True)
    size_kb = out.stat().st_size // 1024
    print(f"✓ Banner: {out}  ({W}x{H}, {size_kb}KB)")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# FOTO DE PERFIL  500 × 500
# ══════════════════════════════════════════════════════════════════════════════

def make_profile() -> Path:
    S = 500
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo circular com gradiente manual
    cx = cy = S // 2
    for r in range(cx, 0, -1):
        ratio = r / cx
        col = (
            int(BG_MID[0] + (BG_DARK[0] - BG_MID[0]) * (1 - ratio)),
            int(BG_MID[1] + (BG_DARK[1] - BG_MID[1]) * (1 - ratio)),
            int(BG_MID[2] + (BG_DARK[2] - BG_MID[2]) * (1 - ratio)),
            255,
        )
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=col)

    # Anel externo vermelho
    draw.ellipse([(4, 4), (S - 4, S - 4)], outline=ACCENT_RED, width=12)

    # Anel interno sutil
    draw.ellipse([(20, 20), (S - 20, S - 20)], outline=(*BLUE_LIGHT, 40), width=2)

    # Letras  B24
    f_b  = font(FONT_BOLD, 180)
    f_24 = font(FONT_BOLD, 100)

    # "B" grande centralizado ligeiramente à esquerda
    b_text = "B"
    bw = int(draw.textlength(b_text, font=f_b)) if hasattr(draw, "textlength") else 130
    draw.text((cx - bw // 2 - 30, cy - 105), b_text, font=f_b, fill=WHITE)

    # "24" em dourado, sobreposto abaixo-direita do B
    t24 = "24"
    t24w = int(draw.textlength(t24, font=f_24)) if hasattr(draw, "textlength") else 110
    draw.text((cx + 30, cy + 20), t24, font=f_24, fill=GOLD)

    # Linha decorativa vermelha
    draw.rectangle([(cx - 80, cy + 10), (cx + 80, cy + 14)], fill=ACCENT_RED)

    # Texto "BRASIL24" pequeno na base
    f_sm = font(FONT_BOLD, 28)
    label = "BRASIL24"
    lw = int(draw.textlength(label, font=f_sm)) if hasattr(draw, "textlength") else 120
    draw.text(((S - lw) // 2, cy + 120), label, font=f_sm, fill=(*GRAY, 200))

    # Máscara circular final (corta bordas para círculo perfeito)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (S - 1, S - 1)], fill=255)
    img.putalpha(mask)

    # Converte para RGB com fundo escuro (PNG com transparência para YouTube)
    out = OUT_DIR / "profile_picture.png"
    img.save(out, "PNG")
    size_kb = out.stat().st_size // 1024
    print(f"✓ Perfil:  {out}  ({S}x{S}, {size_kb}KB)")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CHANNEL INFO  (texto para copiar no YouTube Studio)
# ══════════════════════════════════════════════════════════════════════════════

def make_channel_info() -> Path:
    content = """\
╔══════════════════════════════════════════════════════════════╗
║           BRASIL24 — Pacote de Informações do Canal          ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 NOME DO CANAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Brasil24

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 HANDLE (URL do canal)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@brasil24tv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 DESCRIÇÃO DO CANAL (cole no YouTube Studio → Personalização → Informações básicas)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 BRASIL24 — Notícias do Brasil em Tempo Real | 24 horas por dia

Acompanhe as principais notícias do Brasil com análises aprofundadas, direto ao ponto e sem filtros. O Brasil24 transmite ao vivo 24 horas por dia, 7 dias por semana, com cobertura completa de:

📰 Política nacional e internacional
💰 Economia, mercado financeiro e negócios
🏥 Saúde, ciência e tecnologia
⚽ Esporte, cultura e entretenimento
🌎 Brasil e o mundo

Nossos apresentadores Ana Silva e Carlos Mendes trazem os fatos com profundidade, convidando especialistas de cada área para analisar os temas que mais impactam o seu dia a dia.

✅ Inscreva-se e ative o sininho 🔔 para não perder nenhuma notícia!

📡 Transmissão ao vivo todos os dias — sem interrupção.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TAGS / PALAVRAS-CHAVE (para SEO — cole em "Tags" no YouTube Studio)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
noticias brasil, noticias ao vivo, brasil24, jornal ao vivo, politica brasil, economia brasil, noticias hoje, ao vivo 24 horas, breaking news brasil, noticias urgentes, jornalismo brasileiro, telejornal ao vivo, noticia de hoje, brasil noticias, noticias em tempo real

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LINKS PARA REDES SOCIAIS (opcional — cole em "Links" no YouTube Studio)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instagram: @brasil24tv
X (Twitter): @brasil24tv
Telegram:   t.me/brasil24tv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 EMAIL DE CONTATO (opcional)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
contato@brasil24.tv

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 LOCALIZAÇÃO (opcional — para aparecer em buscas locais)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Brasil

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 COMO USAR OS ARQUIVOS DE IMAGEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. banner_youtube.png  → YouTube Studio → Personalização → Arte do canal → Fazer upload
   Resolução: 2048x1152px (compatível com todos os dispositivos)
   Zona segura para TV: área central de 1546x423px (conteúdo principal visível em todos os devices)

2. profile_picture.png → YouTube Studio → Personalização → Informações básicas → Foto do perfil
   Resolução: 500x500px PNG com transparência
   O YouTube mostrará em formato circular — a imagem já foi criada com fundo circular

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CONFIGURAÇÕES RECOMENDADAS NO YOUTUBE STUDIO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ Personalização → Layout do canal:
  - Trailer do canal: coloque o primeiro episódio gerado
  - Seções: "Transmissões ao vivo" + "Vídeos" + "Em destaque"

→ Configurações → Canal → Informações básicas:
  - Categoria: Notícias e política
  - País: Brasil
  - Palavras-chave: (cole as tags acima)

→ Transmissões ao vivo → Configurações padrão:
  - Título padrão: "🔴 AO VIVO | Brasil24 — Notícias em Tempo Real"
  - Descrição padrão: (cole a descrição do canal acima)
  - Categoria: Notícias e política
  - Feito para crianças: NÃO
  - Visibilidade: Público
"""
    out = OUT_DIR / "channel_info.txt"
    out.write_text(content, encoding="utf-8")
    print(f"✓ Info:    {out}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n🎨 Gerando assets do canal Brasil24...\n")
    make_banner()
    make_profile()
    make_channel_info()
    print(f"\n✅ Tudo salvo em: {OUT_DIR.absolute()}/")
    print("   ├── banner_youtube.png  (2048x1152 — arte do canal)")
    print("   ├── profile_picture.png (500x500   — foto de perfil)")
    print("   └── channel_info.txt    (textos para copiar no YouTube Studio)")
