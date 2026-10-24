"""Günün ilk paylaşımı: TL bazlı piyasa tablosu.

Hafta içi: döviz, gram altın ve kripto/TL. Hafta sonu (FX piyasaları kapalı): kripto ağırlıklı.
Bu kartta yapay zeka kullanılmaz; tüm rakamlar doğrudan veri kaynağından gelir ve kodla biçimlenir.
Gemini kotası harcanmaz."""
from __future__ import annotations

import logging
import random
from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter

from . import card, config
from .sources import SESSION

log = logging.getLogger(__name__)
W, H, M = card.W, card.H, card.M
TR_DAYS = ["PAZARTESİ", "SALI", "ÇARŞAMBA", "PERŞEMBE", "CUMA", "CUMARTESİ", "PAZAR"]
TR_DAYS_TITLE = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
TR_MONTHS_TITLE = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül",
                   "Ekim", "Kasım", "Aralık"]
GRAMS_PER_OUNCE = 31.1034768


# ----------------------------------------------------------------- Biçimleme
def tr_num(v: float, decimals: int) -> str:
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def tr_pct(v: float) -> str:
    arrow = "▲" if v > 0.005 else "▼" if v < -0.005 else "■"
    sign = "+" if v > 0.005 else "−" if v < -0.005 else ""
    return f"{arrow} {sign}%{tr_num(abs(v), 2)}"


# --------------------------------------------------------------------- Veri
def _yahoo_pair(symbol: str) -> tuple[float, float] | None:
    """(son değer, bir önceki kapanış)."""
    r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"range": "5d", "interval": "1d"}, timeout=config.HTTP_TIMEOUT)
    res = r.json()["chart"]["result"][0]
    closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
    if len(closes) < 2:
        return None
    return closes[-1], closes[-2]


def _row(code: str, name: str, value: float, change: float, decimals: int) -> dict:
    return {"code": code, "name": name, "value": value, "change": change,
            "text": tr_num(value, decimals)}


def fetch_rows(weekend: bool) -> list[dict]:
    rows: list[dict] = []
    fx: dict[str, tuple[float, float]] = {}
    for sym in ("USDTRY=X", "EURTRY=X", "GBPTRY=X", "GC=F"):
        try:
            got = _yahoo_pair(sym)
            if got:
                fx[sym] = got
        except Exception as exc:
            log.warning("Kur verisi alınamadı (%s): %s", sym, exc)

    crypto: dict = {}
    ids = "bitcoin,ethereum,solana,ripple,tether"
    try:
        crypto = SESSION.get("https://api.coingecko.com/api/v3/simple/price",
                             params={"ids": ids, "vs_currencies": "try", "include_24hr_change": "true"},
                             timeout=config.HTTP_TIMEOUT).json()
    except Exception as exc:
        log.warning("Kripto/TL verisi alınamadı: %s", exc)

    def fx_row(sym, code, name, dec=4):
        if sym in fx:
            last, prev = fx[sym]
            rows.append(_row(code, name, last, (last / prev - 1) * 100, dec))

    def cg_row(cid, code, name, dec):
        d = crypto.get(cid)
        if d and d.get("try"):
            rows.append(_row(code, name, d["try"], d.get("try_24h_change") or 0.0, dec))

    if not weekend:
        fx_row("USDTRY=X", "USD/TRY", "Amerikan Doları")
        fx_row("EURTRY=X", "EUR/TRY", "Euro")
        fx_row("GBPTRY=X", "GBP/TRY", "İngiliz Sterlini")
        if "GC=F" in fx and "USDTRY=X" in fx:
            (g, gp), (u, up) = fx["GC=F"], fx["USDTRY=X"]
            gram, gram_prev = g * u / GRAMS_PER_OUNCE, gp * up / GRAMS_PER_OUNCE
            rows.append(_row("GRAM ALTIN", "Ons bazlı hesaplama*", gram, (gram / gram_prev - 1) * 100, 2))
        cg_row("bitcoin", "BTC/TRY", "Bitcoin", 0)
        cg_row("tether", "USDT/TRY", "Tether", 3)
    else:
        cg_row("bitcoin", "BTC/TRY", "Bitcoin", 0)
        cg_row("ethereum", "ETH/TRY", "Ethereum", 0)
        cg_row("solana", "SOL/TRY", "Solana", 2)
        cg_row("ripple", "XRP/TRY", "XRP", 2)
        cg_row("tether", "USDT/TRY", "Tether", 3)
        if "USDTRY=X" in fx:
            last, prev = fx["USDTRY=X"]
            rows.append(_row("USD/TRY", "Cuma kapanışı", last, (last / prev - 1) * 100, 4))

    # Bozuk veri koruması: sıfır/negatif değer veya bir günde %25'ten büyük değişim gösterilmez
    clean = [r for r in rows if r["value"] > 0 and abs(r["change"]) < 25]
    for r in rows:
        if r not in clean:
            log.warning("Şüpheli veri atlandı: %s", r)
    return clean


# --------------------------------------------------------------------- Metin
def build_caption(rows: list[dict], now: datetime, weekend: bool) -> str:
    day = f"{now.day} {TR_MONTHS_TITLE[now.month - 1]} {TR_DAYS_TITLE[now.weekday()]}"
    if weekend:
        hook = f"Günaydın. Döviz piyasaları hafta sonu kapalı; kripto piyasası ise 7/24 işlemde. {day} itibarıyla TL bazlı kripto tablosu:"
        cta = "Hafta sonu hangi varlığı yakından takip ediyorsunuz?"
    else:
        hook = f"Günaydın. {day} sabahı TL karşısında piyasaların görünümü:"
        cta = "Bugün en çok hangi kuru takip ediyorsunuz?"
    lines = [hook, ""]
    for r in rows:
        lines.append(f"{tr_pct(r['change']).split(' ')[0]} {r['code']}: {r['text']} TL "
                     f"({tr_pct(r['change']).split(' ', 1)[1]})")
    lines += [""]
    if any(r["code"] == "GRAM ALTIN" for r in rows):
        lines.append("*Gram altın, ons altın (USD) ve USD/TRY üzerinden hesaplanmıştır; kuyumcu fiyatlarından farklılık gösterebilir.")
    lines += [
        f"Veriler {now:%H:%M} (TSİ) itibarıyla piyasa verisidir; döviz için günlük, kripto için 24 saatlik değişim.",
        "",
        cta,
        "",
        config.DISCLAIMER,
        "",
        config.HASHTAGS + " #Dolar #Euro #Altın #Döviz #Kur",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------- Kart
def render(rows: list[dict], now: datetime, weekend: bool) -> Image.Image:
    bg = card.background_procedural(int(now.strftime("%Y%m%d")))
    img = card._overlay(bg)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    badge = "HAFTA SONU KRİPTO TABLOSU" if weekend else "GÜNLÜK PİYASA TABLOSU"
    f_badge = card.font("SemiBold", 22)
    bw = card.spaced_width(d, badge, f_badge, 2.4) + 48
    d.rounded_rectangle((M, M, M + bw, M + 50), radius=25, fill=card.CYAN + (28,), outline=card.CYAN + (220,), width=2)
    card.draw_spaced(d, (M + 24, M + 12), badge, f_badge, card.CYAN + (255,), 2.4)
    stamp = f"{now:%H:%M} TSİ"
    f_date = card.font("Medium", 22)
    d.text((W - M - d.textlength(stamp, font=f_date), M + 13), stamp, font=f_date, fill=card.GREY + (255,))

    y = M + 50 + 56
    d.text((M, y), "GÜNAYDIN", font=card.font("ExtraBold", 84), fill=card.WHITE + (255,))
    y += 98
    sub = f"{now.day} {card.TR_MONTHS[now.month - 1]} {TR_DAYS[now.weekday()]}"
    d.text((M, y), sub, font=card.font("SemiBold", 34), fill=card.CYAN + (255,))
    y += 66

    # Tablo
    n = len(rows)
    f_chg = card.font("Bold", 26)
    pill_w = max(d.textlength(tr_pct(r["change"]), font=f_chg) for r in rows) + 28   # hizalı sütun
    row_h = min(118, (H - M - 150 - y) // max(n, 1))
    for i, r in enumerate(rows):
        top = y + i * row_h
        box = (M, top, W - M, top + row_h - 14)
        d.rounded_rectangle(box, radius=16, fill=card.PANEL + (210,), outline=(120, 170, 220, 45), width=1)
        mid = top + (row_h - 14) // 2
        f_code, f_name = card.font("ExtraBold", 34), card.font("Medium", 20)
        d.text((M + 28, mid - 30), r["code"], font=f_code, fill=card.WHITE + (255,))
        d.text((M + 28, mid + 10), r["name"], font=f_name, fill=card.GREY + (255,))
        up, down = r["change"] > 0.005, r["change"] < -0.005
        color = card.GREEN if up else card.RED if down else card.GREY
        chg = tr_pct(r["change"])
        cw = d.textlength(chg, font=f_chg)
        pill = (W - M - 28 - pill_w, mid - 22, W - M - 28, mid + 22)
        d.rounded_rectangle(pill, radius=22, fill=color + (36,), outline=color + (150,), width=1)
        d.text((pill[2] - 14 - cw, mid - 16), chg, font=f_chg, fill=color + (255,))
        val = r["text"]
        f_val = card._fit(d, val, "ExtraBold", 46, 30, pill[0] - 40 - (M + 300))
        d.text((pill[0] - 28 - d.textlength(val, font=f_val), mid - f_val.size * 0.62), val, font=f_val,
               fill=card.WHITE + (255,))

    # Alt bilgi
    footer_y = H - M - 34
    note = ("Kripto: 24 saatlik değişim · USD/TRY: cuma kapanışı" if weekend
            else "Döviz: günlük değişim · Kripto: 24 saatlik · *Ons ve USD/TRY bazlı")
    f_note = card.font("Medium", 19)
    d.text((M, footer_y - 64), note, font=f_note, fill=card.DIM + (255,))
    d.line([(M, footer_y - 26), (W - M, footer_y - 26)], fill=(120, 170, 220, 60), width=1)
    d.rectangle((M, footer_y + 6, M + 12, footer_y + 18), fill=card.CYAN + (255,))
    card.draw_spaced(d, (M + 26, footer_y), config.SIGNATURE, card.font("Bold", 24), card.WHITE + (255,), 1.6)
    src = "Yahoo Finance · CoinGecko"
    f_src = card.font("Medium", 20)
    d.text((W - M - d.textlength(src, font=f_src), footer_y + 4), src, font=f_src, fill=card.DIM + (255,))

    return Image.alpha_composite(img, layer).convert("RGB")


def build_post(now: datetime) -> tuple[dict, Image.Image] | None:
    weekend = now.weekday() >= 5
    rows = fetch_rows(weekend)
    if len(rows) < 4:
        log.warning("Kur tablosu için yeterli veri yok (%d satır).", len(rows))
        return None
    sub = f"{now.day} {card.TR_MONTHS[now.month - 1]} {TR_DAYS[now.weekday()]}"
    post = {
        "type": "rates",
        "category": "HAFTA SONU KRİPTO TABLOSU" if weekend else "GÜNLÜK PİYASA TABLOSU",
        "headline": f"GÜNAYDIN · {sub}",
        "rows": rows,
        "caption": build_caption(rows, now, weekend),
        "source_name": "Yahoo Finance, CoinGecko",
        "source_link": "",
        "source_title": f"Günlük kur tablosu {now:%Y-%m-%d}",
    }
    return post, render(rows, now, weekend)
