"""Instagram kartı (1080x1350 JPEG): Flux arka planı + Pillow ile tipografi.

Arka plan Cloudflare Workers AI üzerindeki ücretsiz Flux-1-schnell ile üretilir.
Anahtar yoksa veya servis yanıt vermezse kodla üretilen terminal estetiğinde
bir arka plana düşülür; böylece paylaşım hiçbir koşulda görselsiz kalmaz."""
from __future__ import annotations

import base64
import io
import logging
import math
import os
import random
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config

log = logging.getLogger(__name__)
W, H = config.CARD_W, config.CARD_H
M = 72  # kenar boşluğu

NAVY = (7, 13, 26)
PANEL = (12, 22, 40)
CYAN = (56, 225, 245)
AMBER = (245, 184, 61)
WHITE = (241, 245, 250)
GREY = (150, 164, 186)
DIM = (92, 106, 130)
GREEN = (52, 211, 153)
RED = (248, 113, 113)

TR_MONTHS = ["OCAK", "ŞUBAT", "MART", "NİSAN", "MAYIS", "HAZİRAN", "TEMMUZ", "AĞUSTOS", "EYLÜL",
             "EKİM", "KASIM", "ARALIK"]
_EMOJI_RE = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]+")


# Türkçe büyük harf kuralı (i -> İ) yabancı marka adlarına uygulanmaz: BITCOIN, NVIDIA...
FOREIGN_WORDS = {
    "bitcoin", "coinbase", "binance", "nvidia", "fidelity", "microsoft", "ripple", "chainlink", "bitwise",
    "bitfinex", "circle", "microstrategy", "robinhood", "arbitrum", "polkadot", "litecoin", "dogecoin",
    "stablecoin", "stablecoin'ler", "altcoin", "memecoin", "invesco", "franklin", "ishares", "citi",
    "citigroup", "visa", "bitstamp", "kraken", "gemini", "meta", "intel", "qualcomm", "micron", "broadcom",
    "alibaba", "openai", "anthropic", "silicon", "tokenization", "defi", "bitmine", "trump", "wall",
    "bitcoin'in", "bitcoin'e", "bitcoin'de", "bitcoin'den", "nvidia'nın", "nvidia'ya", "coinbase'in",
    "binance'in", "mining", "chips", "ai",
}


def _is_foreign(word: str) -> bool:
    core = re.sub(r"[^\w'’]", "", word.lower())
    base = re.split(r"['’]", core)[0]
    return (core in FOREIGN_WORDS or base in FOREIGN_WORDS or any(c in base for c in "qwx")
            or base.endswith(("coin", "chain", "bit")))


def tr_upper(s: str) -> str:
    out = []
    for word in s.split(" "):
        if _is_foreign(word):
            parts = re.split(r"(['’])", word, maxsplit=1)
            base = parts[0]
            suffix = "".join(parts[1:])           # Türkçe ek (kesme işaretinden sonrası)
            out.append(base.upper() + suffix.replace("i", "İ").replace("ı", "I").upper())
        else:
            out.append(word.replace("i", "İ").replace("ı", "I").upper())
    return " ".join(out)


def strip_emoji(s: str) -> str:
    return _EMOJI_RE.sub("", s).strip()


# ------------------------------------------------------------------- Yazı tipi
_FONT_CACHE: dict = {}


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _FONT_CACHE:
        path = config.FONTS_DIR / f"Inter-{weight}.otf"
        try:
            _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
        except OSError:
            bold = "Bold" in weight or weight in ("Black", "SemiBold")
            fallback = "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if bold else "") + ".ttf"
            _FONT_CACHE[key] = ImageFont.truetype(fallback, size)
    return _FONT_CACHE[key]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def draw_spaced(draw, xy, text, fnt, fill, spacing=2.0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + spacing
    return x


def spaced_width(draw, text, fnt, spacing=2.0) -> float:
    return sum(draw.textlength(ch, font=fnt) + spacing for ch in text) - spacing


# ------------------------------------------------------------------ Arka plan
def background_from_cloudflare(prompt: str) -> Image.Image | None:
    acct, token = (os.getenv("CF_ACCOUNT_ID") or "").strip(), (os.getenv("CF_API_TOKEN") or "").strip()
    if not (acct and token):
        log.info("Cloudflare anahtarı yok, kodla üretilen arka plan kullanılacak.")
        return None
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    prompt = ((prompt or "").strip()[:1700] +
              ", cinematic, no screens with numbers, no typography, no brand logos, no characters, no watermark")
    attempts = ({"prompt": prompt, "steps": 6}, {"prompt": prompt})   # ikincisi: en sade istek
    try:
        for body in attempts:
            r = requests.post(url, headers={"Authorization": f"Bearer {token.strip()}"},
                              json=body, timeout=120)
            if r.ok:
                break
            log.warning("Cloudflare yanıtı HTTP %s: %s", r.status_code, r.text[:400])
        r.raise_for_status()
        b64 = r.json()["result"]["image"]
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        log.info("Flux arka planı üretildi (%sx%s).", *img.size)
        return img
    except Exception as exc:
        log.warning("Flux arka planı üretilemedi, yedek kullanılacak: %s", exc)
        return None


def background_procedural(seed: int) -> Image.Image:
    """Koyu lacivert zeminde neon veri çizgileri ve ızgara (yedek arka plan)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(H):  # dikey degrade
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(9 + 10 * (1 - t)), int(16 + 14 * (1 - t)), int(34 + 22 * (1 - t))))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for i in range(5):  # fiyat grafiği benzeri neon çizgiler
        color = [CYAN, (120, 110, 255), AMBER, CYAN, (80, 160, 255)][i]
        y = rnd.randint(int(H * 0.25), int(H * 0.75))
        pts, x = [], -20
        while x < W + 40:
            y += rnd.gauss(-1.2, 22)
            y = max(H * 0.15, min(H * 0.85, y))
            pts.append((x, y))
            x += rnd.randint(18, 42)
        g.line(pts, fill=color + (170 if i < 2 else 90,), width=3 if i < 2 else 2)
    blurred = glow.filter(ImageFilter.GaussianBlur(9))
    img = Image.alpha_composite(img.convert("RGBA"), blurred)
    img = Image.alpha_composite(img, glow)
    return img.convert("RGB")


def cover(img: Image.Image) -> Image.Image:
    scale = max(W / img.width, H / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def _overlay(base: Image.Image) -> Image.Image:
    """Okunabilirlik için hafif bulanıklık + degrade karartma + ince terminal ızgarası.
    Bulanıklık, yapay zekanın arka plana istemeden çizdiği anlamsız yazı/rakamları da gizler."""
    base = base.filter(ImageFilter.GaussianBlur(3))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(H):
        t = y / H
        a = 160 if t < 0.45 else int(160 + (t - 0.45) / 0.55 * 85)   # alta doğru koyulaşır
        if t < 0.08:
            a = 200
        d.line([(0, y), (W, y)], fill=NAVY + (min(a, 245),))
    for x in range(0, W, 54):
        d.line([(x, 0), (x, H)], fill=(120, 170, 220, 14))
    for y in range(0, H, 54):
        d.line([(0, y), (W, y)], fill=(120, 170, 220, 14))
    return Image.alpha_composite(base.convert("RGBA"), ov)


# ------------------------------------------------------------------ Kart çizimi
def _panel(d: ImageDraw.ImageDraw, box, accent):
    d.rounded_rectangle(box, radius=18, fill=PANEL + (215,), outline=accent + (90,), width=2)
    x0, y0, x1, _ = box
    d.rounded_rectangle((x0 + 28, y0, x0 + 92, y0 + 5), radius=2, fill=accent + (255,))


def _fit(d, text, weight, start, min_size, max_w):
    size = start
    while size > min_size and d.textlength(text, font=font(weight, size)) > max_w:
        size -= 2
    return font(weight, size)


def render_card(post: dict, background: Image.Image, when: datetime | None = None) -> Image.Image:
    when = when or datetime.now(ZoneInfo("Europe/Istanbul"))
    img = _overlay(cover(background))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    # Üst şerit: kategori rozeti + tarih
    cat = strip_emoji(post["category"]).upper()
    f_badge = font("SemiBold", 22)
    bw = spaced_width(d, cat, f_badge, 2.4) + 48
    d.rounded_rectangle((M, M, M + bw, M + 50), radius=25, fill=CYAN + (28,), outline=CYAN + (220,), width=2)
    draw_spaced(d, (M + 24, M + 12), cat, f_badge, CYAN + (255,), 2.4)
    stamp = f"{when.day} {TR_MONTHS[when.month - 1]} {when.year}  ·  {when:%H:%M} TSİ"
    f_date = font("Medium", 22)
    d.text((W - M - d.textlength(stamp, font=f_date), M + 13), stamp, font=f_date, fill=GREY + (255,))

    # Manşet: sığana kadar küçült (en fazla 4 satır)
    headline = tr_upper(strip_emoji(post["headline"]))
    for size in range(88, 50, -4):
        f_head = font("ExtraBold", size)
        lines = wrap(d, headline, f_head, W - 2 * M)
        if len(lines) <= 4:
            break
    y = M + 50 + 70
    line_h = int(f_head.size * 1.1)
    for ln in lines:
        d.text((M, y), ln, font=f_head, fill=WHITE + (255,))
        y += line_h
    y += 22
    d.rectangle((M, y, M + 110, y + 6), fill=CYAN + (255,))

    # Borsa kodu etiketi (ör. NVDA  −%3,24) — yalnızca şirket/varlık haberlerinde
    q = post.get("quote")
    if q:
        up = q["change"] >= 0
        color = GREEN if up else RED
        chg = f"{'+' if up else '−'}%{abs(q['change']):.2f}".replace(".", ",")
        f_sym, f_chg = font("ExtraBold", 30), font("Bold", 30)
        sw, cw = d.textlength(q["symbol"], font=f_sym), d.textlength(chg, font=f_chg)
        bw2 = int(sw + cw + 28 * 2 + 22)
        bx1, by0 = W - M, y + 30
        bx0 = bx1 - bw2
        d.rounded_rectangle((bx0, by0, bx1, by0 + 60), radius=12, fill=PANEL + (225,),
                            outline=color + (160,), width=2)
        d.text((bx0 + 28, by0 + 13), q["symbol"], font=f_sym, fill=WHITE + (255,))
        d.text((bx0 + 28 + sw + 22, by0 + 13), chg, font=f_chg, fill=color + (255,))

    # Alt bölüm aşağıdan yukarıya yerleştirilir
    footer_y = H - M - 34
    f_sig = font("Bold", 24)
    d.line([(M, footer_y - 26), (W - M, footer_y - 26)], fill=(120, 170, 220, 60), width=1)
    d.rectangle((M, footer_y + 6, M + 12, footer_y + 18), fill=CYAN + (255,))
    draw_spaced(d, (M + 26, footer_y), config.SIGNATURE, f_sig, WHITE + (255,), 1.6)
    src = post.get("source_name", "")
    if src:
        f_src = font("Medium", 20)
        txt = f"Kaynak: {src}"
        d.text((W - M - d.textlength(txt, font=f_src), footer_y + 4), txt, font=f_src, fill=DIM + (255,))

    # Özet paneli
    f_sum = font("Regular", 30)
    sum_lines = wrap(d, strip_emoji(post["summary"]), f_sum, W - 2 * M - 64)[:6]
    sum_h = 56 + len(sum_lines) * 43 + 30
    sum_bottom = footer_y - 50
    sum_top = sum_bottom - sum_h
    d.rounded_rectangle((M, sum_top, W - M, sum_bottom), radius=18, fill=PANEL + (200,),
                        outline=(120, 170, 220, 50), width=1)
    draw_spaced(d, (M + 32, sum_top + 26), "ÖZET VE İÇGÖRÜ", font("SemiBold", 19), GREY + (255,), 2.2)
    ty = sum_top + 64
    for ln in sum_lines:
        d.text((M + 32, ty), ln, font=f_sum, fill=(214, 222, 234, 255))
        ty += 43

    # Metrik panelleri
    gap = 24
    pw = (W - 2 * M - gap) // 2
    ph = 190
    p_top = sum_top - 28 - ph
    for i, (key, accent) in enumerate((("metric1", CYAN), ("metric2", AMBER))):
        x0 = M + i * (pw + gap)
        _panel(d, (x0, p_top, x0 + pw, p_top + ph), accent)
        label = strip_emoji(post[key]["label"])
        f_lab = font("Medium", 24)
        lab_lines = wrap(d, label, f_lab, pw - 56)[:2]
        ly = p_top + 34
        for ln in lab_lines:
            d.text((x0 + 28, ly), ln, font=f_lab, fill=GREY + (255,))
            ly += 32
        value = strip_emoji(post[key]["value"])
        f_val = _fit(d, value, "ExtraBold", 60, 34, pw - 56)
        d.text((x0 + 28, p_top + ph - 34 - f_val.size), value, font=f_val, fill=accent + (255,))

    # Manşet metrik panellerine taşarsa uyar (render yine de devam eder)
    if y + 6 > p_top - 20:
        log.warning("Manşet alanı sıkışık: manşet altı %d, panel üstü %d", y, p_top)

    out = Image.alpha_composite(img, layer).convert("RGB")
    return out


def build_card(post: dict, seed: int, when: datetime | None = None) -> Image.Image:
    bg = background_from_cloudflare(post["image_prompt"]) or background_procedural(seed)
    return render_card(post, bg, when)
