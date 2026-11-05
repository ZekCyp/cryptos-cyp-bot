"""Haber gönderisi için ek kaydırmalı slaytlar (carousel).

Slayt 2: "Neden önemli?" — doğrulamadan geçmiş üç piyasa etkisi maddesi.
Slayt 3: 30 günlük fiyat grafiği — veriler doğrudan Yahoo Finance'ten gelir, modelden değil.
Bu slaytlar Gemini kotası harcamaz. Grafik verisi alınamazsa gönderi 2 slaytla çıkar."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw

from . import card, config
from .sources import SESSION

log = logging.getLogger(__name__)
W, H, M = card.W, card.H, card.M

# Kategoriye göre grafik sembolü (haberde belirli bir şirket/varlık yoksa)
CATEGORY_CHART = [
    (["ETF", "FLOWS", "CRYPTO", "WEB3", "REGULATION"], "BTC-USD", "Bitcoin", "USD"),
    (["SEMICONDUCTOR"], "^SOX", "Yarı İletken Endeksi (SOX)", "Puan"),
    (["GEOPOLITIC"], "BZ=F", "Brent Petrol", "USD/varil"),
    (["MACRO", "CENTRAL"], "DX-Y.NYB", "Dolar Endeksi (DXY)", "Puan"),
    (["GLOBAL MARKETS", "AI", "CORPORATE", "LEGAL"], "^IXIC", "Nasdaq Bileşik", "Puan"),
]
MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
          "Kasım", "Aralık"]
TICKER_LABELS = {"BTC": ("Bitcoin", "USD"), "ETH": ("Ethereum", "USD"), "SOL": ("Solana", "USD"),
                 "XRP": ("XRP", "USD")}


def tr_num(v: float, decimals: int) -> str:
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _decimals(v: float) -> int:
    return 0 if v >= 1000 else 2 if v >= 1 else 4


# ------------------------------------------------------------------ Ortak çerçeve
def _frame(seed: int, badge: str, page: str) -> tuple[Image.Image, Image.Image, ImageDraw.ImageDraw]:
    img = card._overlay(card.background_procedural(seed))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f_badge = card.font("SemiBold", 22)
    bw = card.spaced_width(d, badge, f_badge, 2.4) + 48
    d.rounded_rectangle((M, M, M + bw, M + 50), radius=25, fill=card.CYAN + (28,),
                        outline=card.CYAN + (220,), width=2)
    card.draw_spaced(d, (M + 24, M + 12), badge, f_badge, card.CYAN + (255,), 2.4)
    f_page = card.font("Medium", 22)
    d.text((W - M - d.textlength(page, font=f_page), M + 13), page, font=f_page, fill=card.GREY + (255,))
    return img, layer, d


def _footer(d: ImageDraw.ImageDraw, right: str) -> None:
    footer_y = H - M - 34
    d.line([(M, footer_y - 26), (W - M, footer_y - 26)], fill=(120, 170, 220, 60), width=1)
    d.rectangle((M, footer_y + 6, M + 12, footer_y + 18), fill=card.CYAN + (255,))
    card.draw_spaced(d, (M + 26, footer_y), config.SIGNATURE, card.font("Bold", 24), card.WHITE + (255,), 1.6)
    f = card.font("Medium", 20)
    d.text((W - M - d.textlength(right, font=f), footer_y + 4), right, font=f, fill=card.DIM + (255,))


# ------------------------------------------------------------ Slayt 2: etkiler
def render_impacts(post: dict, seed: int, total: int) -> Image.Image:
    img, layer, d = _frame(seed, "NEDEN ÖNEMLİ?", f"2 / {total}")
    y = M + 50 + 60
    f_title = card.font("ExtraBold", 64)
    for ln in card.wrap(d, "PİYASAYA ETKİSİ", f_title, W - 2 * M):
        d.text((M, y), ln, font=f_title, fill=card.WHITE + (255,))
        y += 76
    y += 6
    d.rectangle((M, y, M + 110, y + 6), fill=card.CYAN + (255,))
    y += 44

    items = [("01", "Kurumsal Oyuncular ve Likidite", post["impacts"]["institutional"], card.CYAN),
             ("02", "Fiyat / Trend Dinamikleri", post["impacts"]["price"], card.AMBER),
             ("03", "Küçük Yatırımcı İçin Risk / Fırsat", post["impacts"]["retail"], card.GREEN)]
    bottom = H - M - 34 - 60
    avail = bottom - y - 2 * 22
    f_body = card.font("Regular", 29)
    # Metin sığana kadar yazı boyutunu küçült
    for size in (34, 32, 30, 28, 26, 24):
        f_body = card.font("Regular", size)
        heights = [76 + len(card.wrap(d, card.strip_emoji(t), f_body, W - 2 * M - 64)) * int(size * 1.42) + 28
                   for _, _, t, _ in items]
        if sum(heights) <= avail:
            break
    for (num, label, text, color), h in zip(items, heights):
        h = min(h, (avail // 3) + 60)
        d.rounded_rectangle((M, y, W - M, y + h), radius=18, fill=card.PANEL + (215,),
                            outline=color + (90,), width=2)
        d.rounded_rectangle((M + 28, y, M + 92, y + 5), radius=2, fill=color + (255,))
        d.text((M + 32, y + 26), num, font=card.font("ExtraBold", 26), fill=color + (255,))
        d.text((M + 84, y + 28), card.tr_upper(label), font=card.font("SemiBold", 22), fill=card.GREY + (255,))
        ty = y + 76
        for ln in card.wrap(d, card.strip_emoji(text), f_body, W - 2 * M - 64):
            if ty + f_body.size > y + h - 12:
                break
            d.text((M + 32, ty), ln, font=f_body, fill=(214, 222, 234, 255))
            ty += int(f_body.size * 1.42)
        y += h + 22
    _footer(d, "Kaydet · Paylaş")
    return Image.alpha_composite(img, layer).convert("RGB")


# ------------------------------------------------------------ Slayt 3: grafik
def chart_symbol(post: dict) -> tuple[str, str, str]:
    q = post.get("quote")
    if q and post.get("ticker"):
        sym = q["symbol"]
        name, unit = TICKER_LABELS.get(sym, (sym, "USD"))
        return post["ticker"], name, unit
    cat = (post.get("category") or "").upper()
    for words, sym, name, unit in CATEGORY_CHART:
        if any(w in cat for w in words):
            return sym, name, unit
    return "^IXIC", "Nasdaq Bileşik", "Puan"


def fetch_series(symbol: str, days: int = 30) -> list[tuple[datetime, float]]:
    r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"range": "3mo", "interval": "1d"}, timeout=config.HTTP_TIMEOUT)
    res = r.json()["chart"]["result"][0]
    pts = [(datetime.fromtimestamp(t, tz=timezone.utc), c)
           for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]) if c is not None]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [p for p in pts if p[0] >= cutoff]


def render_chart(series: list[tuple[datetime, float]], name: str, unit: str, seed: int,
                 total: int) -> Image.Image:
    img, layer, d = _frame(seed, "30 GÜNLÜK GÖRÜNÜM", f"3 / {total}")
    first, last = series[0][1], series[-1][1]
    chg = (last / first - 1) * 100
    up = chg >= 0
    color = card.GREEN if up else card.RED
    dec = _decimals(last)

    y = M + 50 + 60
    f_name = card._fit(d, card.tr_upper(name), "ExtraBold", 64, 40, W - 2 * M)
    d.text((M, y), card.tr_upper(name), font=f_name, fill=card.WHITE + (255,))
    y += f_name.size + 26
    d.text((M, y), tr_num(last, dec), font=card.font("ExtraBold", 80), fill=card.WHITE + (255,))
    vw = d.textlength(tr_num(last, dec), font=card.font("ExtraBold", 80))
    d.text((M + vw + 18, y + 40), unit, font=card.font("Medium", 26), fill=card.GREY + (255,))
    y += 104
    sign = "+" if up else "−"
    pill_txt = f"{'▲' if up else '▼'} {sign}%{tr_num(abs(chg), 2)}  ·  30 gün"
    f_pill = card.font("Bold", 28)
    pw = d.textlength(pill_txt, font=f_pill) + 40
    d.rounded_rectangle((M, y, M + pw, y + 54), radius=27, fill=color + (36,), outline=color + (160,), width=2)
    d.text((M + 20, y + 11), pill_txt, font=f_pill, fill=color + (255,))
    vals_all = [v for _, v in series]
    rng = f"Zirve {tr_num(max(vals_all), dec)}  ·  Dip {tr_num(min(vals_all), dec)}"
    d.text((M + pw + 24, y + 14), rng, font=card.font("Medium", 24), fill=card.GREY + (255,))
    y += 90

    # Grafik alanı
    gx0, gx1 = M + 8, W - M - 8
    gy0, gy1 = y + 20, H - M - 34 - 130
    vals = [v for _, v in series]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo, hi = lo - pad, hi + pad
    d.rounded_rectangle((M, gy0 - 20, W - M, gy1 + 60), radius=18, fill=card.PANEL + (190,),
                        outline=(120, 170, 220, 45), width=1)
    for i in range(1, 4):  # yatay kılavuz çizgileri
        gy = gy0 + (gy1 - gy0) * i / 4
        d.line([(gx0 + 12, gy), (gx1 - 12, gy)], fill=(120, 170, 220, 28), width=1)

    def pt(i, v):
        x = gx0 + 24 + (gx1 - gx0 - 48) * i / max(len(vals) - 1, 1)
        return x, gy1 - (v - lo) / (hi - lo) * (gy1 - gy0)

    pts = [pt(i, v) for i, v in enumerate(vals)]
    area = pts + [(pts[-1][0], gy1), (pts[0][0], gy1)]
    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(fill_layer).polygon(area, fill=color + (40,))
    layer = Image.alpha_composite(layer, fill_layer)
    d = ImageDraw.Draw(layer)
    d.line(pts, fill=color + (255,), width=5, joint="curve")
    lx, ly = pts[-1]
    d.ellipse((lx - 10, ly - 10, lx + 10, ly + 10), fill=color + (255,))

    f_ax = card.font("Medium", 20)
    for (dt, _), anchor in ((series[0], "l"), (series[-1], "r")):
        txt = f"{dt.day} {MONTHS[dt.month - 1]}"
        x = gx0 + 24 if anchor == "l" else gx1 - 24 - d.textlength(txt, font=f_ax)
        d.text((x, gy1 + 16), txt, font=f_ax, fill=card.GREY + (255,))

    _footer(d, "Veri: Yahoo Finance · günlük kapanış")
    return Image.alpha_composite(img, layer).convert("RGB")


# ------------------------------------------------------------------ Üst düzey
LAST_CHART: tuple | None = None   # (seri, ad, birim) — Reels videosu da kullanır


def build_extra_slides(post: dict, seed: int) -> list[Image.Image]:
    global LAST_CHART
    chart_img = None
    LAST_CHART = None
    try:
        sym, name, unit = chart_symbol(post)
        series = fetch_series(sym)
        if len(series) >= 10 and all(v > 0 for _, v in series):
            LAST_CHART = (series, name, unit)
            chart_img = render_chart(series, name, unit, seed + 2, 3)
        else:
            log.warning("Grafik için yeterli veri yok (%s, %d nokta).", sym, len(series))
    except Exception as exc:
        log.warning("Grafik slaytı üretilemedi: %s", exc)
    try:
        impacts = render_impacts(post, seed + 1, 3 if chart_img else 2)
    except Exception as exc:
        log.warning("Etki slaytı üretilemedi: %s", exc)
        return []
    return [impacts] + ([chart_img] if chart_img else [])


# ------------------------------------------------------- Haber hikâyesi (9:16)
def build_post_story(card_img: Image.Image, has_more: bool = True) -> Image.Image:
    """Gönderi kartının dikey hikâye sürümü (1080x1920). Instagram arayüzü üst ve alt ~250 pikseli
    kapattığı için kart ortalanır, yönlendirme yazısı alttaki güvenli alanın hemen üstüne konur."""
    SW, SH = 1080, 1920
    bg = card.background_procedural(7).resize((SW, SH), Image.LANCZOS).convert("RGBA")
    ov = Image.new("RGBA", (SW, SH), card.NAVY + (215,))
    canvas = Image.alpha_composite(bg, ov)
    ui = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))   # yarı saydam öğeler ayrı katmanda çizilir
    d = ImageDraw.Draw(ui)

    badge = "YENİ ANALİZ"
    f_badge = card.font("SemiBold", 26)
    bw = card.spaced_width(d, badge, f_badge, 3) + 56
    bx = (SW - bw) // 2
    d.rounded_rectangle((bx, 262, bx + bw, 262 + 58), radius=29, fill=card.CYAN + (36,),
                        outline=card.CYAN + (230,), width=2)
    card.draw_spaced(d, (bx + 28, 262 + 14), badge, f_badge, card.CYAN + (255,), 3)

    cw = 940
    ch = int(card_img.height * cw / card_img.width)          # 1175
    top = 262 + 58 + 34
    shadow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(((SW - cw) // 2 - 6, top - 6, (SW + cw) // 2 + 6, top + ch + 6),
                                             radius=28, outline=card.CYAN + (90,), width=3)
    canvas = Image.alpha_composite(canvas, shadow)
    canvas = Image.alpha_composite(canvas, ui)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw, ch), radius=24, fill=255)
    canvas.paste(card_img.resize((cw, ch), Image.LANCZOS), ((SW - cw) // 2, top), mask)

    ui = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(ui)
    cta = "Analiz ve 30 günlük grafik profilde  ↗" if has_more else "Detaylı analiz profilde  ↗"
    f_cta = card.font("Bold", 34)
    tw = d.textlength(cta, font=f_cta)
    y = top + ch + 40
    d.rounded_rectangle(((SW - tw) // 2 - 36, y, (SW + tw) // 2 + 36, y + 76), radius=38,
                        fill=card.PANEL + (240,), outline=card.CYAN + (200,), width=2)
    d.text(((SW - tw) // 2, y + 18), cta, font=f_cta, fill=card.WHITE + (255,))
    return Image.alpha_composite(canvas, ui).convert("RGB")
