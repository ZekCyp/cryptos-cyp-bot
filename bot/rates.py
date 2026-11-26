"""Sabah (09:00) içerikleri. Yapay zeka kullanılmaz; tüm rakamlar doğrudan veri kaynağından gelir.

- HİKÂYE (her gün): güncel kurlar. Anlık veri olduğu için 24 saatte kaybolan hikâye formatında.
  Hafta içi döviz + altın + kripto/TL, hafta sonu kripto ağırlıklı.
- GÖNDERİ (salı-cumartesi): bir önceki işlem gününün KAPANIŞ özeti. Kapanış değerleri tarihsel
  gerçek olduğu için akışta kalıcı olarak doğru kalır. Pazar ve pazartesi sabahı yeni kapanış
  olmadığından gönderi yerine haber paylaşılır."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from PIL import Image, ImageDraw

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


# ------------------------------------------------------------ Kapanış verisi
def _yahoo_daily(symbol: str) -> list[tuple[date, float]]:
    """Günlük kapanışlar: [(borsa saatine göre tarih, kapanış), ...]"""
    r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    params={"range": "15d", "interval": "1d"}, timeout=config.HTTP_TIMEOUT)
    res = r.json()["chart"]["result"][0]
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    out = []
    for ts, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0]["close"]):
        if c is not None:
            out.append(((datetime.fromtimestamp(ts, tz=timezone.utc) + off).date(), c))
    return out


def _close_on(series: list[tuple[date, float]], day: date) -> tuple[float, float] | None:
    """(o günün kapanışı, bir önceki işlem gününün kapanışı)"""
    for i, (d, c) in enumerate(series):
        if d == day and i > 0:
            return c, series[i - 1][1]
    return None


CLOSE_SYMBOLS = [  # (yahoo, kod, birim/ad, ondalık)
    ("USDTRY=X", "USD/TRY", "TL", 4),
    ("EURTRY=X", "EUR/TRY", "TL", 4),
    ("XU100.IS", "BIST 100", "Puan", 2),
    ("^IXIC", "NASDAQ", "Puan", 2),
    ("BZ=F", "BRENT", "USD/varil", 2),
    ("BTC-USD", "BITCOIN", "USD (UTC kapanışı)", 0),
]


def fetch_close_rows(day: date) -> list[dict]:
    series: dict[str, list] = {}
    for sym in [c[0] for c in CLOSE_SYMBOLS] + ["GC=F"]:
        try:
            series[sym] = _yahoo_daily(sym)
        except Exception as exc:
            log.warning("Kapanış verisi alınamadı (%s): %s", sym, exc)
    rows = []
    for sym, code, unit, dec in CLOSE_SYMBOLS:
        got = _close_on(series.get(sym, []), day)
        if got:
            rows.append(_row(code, unit, got[0], (got[0] / got[1] - 1) * 100, dec))
        if code == "EUR/TRY":  # gram altın, döviz satırlarının hemen ardından
            g, u = _close_on(series.get("GC=F", []), day), _close_on(series.get("USDTRY=X", []), day)
            if g and u:
                gram, gram_prev = g[0] * u[0] / GRAMS_PER_OUNCE, g[1] * u[1] / GRAMS_PER_OUNCE
                rows.append(_row("GRAM ALTIN", "TL · ons bazlı*", gram, (gram / gram_prev - 1) * 100, 2))
    clean = [r for r in rows if r["value"] > 0 and abs(r["change"]) < 25]
    return clean


def build_close_caption(rows: list[dict], day: date) -> str:
    dstr = f"{day.day} {TR_MONTHS_TITLE[day.month - 1]} {TR_DAYS_TITLE[day.weekday()]}"
    lines = [f"Günaydın. Dünü nasıl kapattık? {dstr} kapanış verileri:", ""]
    for r in rows:
        arrow, pct = tr_pct(r["change"]).split(" ", 1)
        unit = r["name"].split(" ")[0]
        unit = "TL" if unit.startswith("TL") else unit
        lines.append(f"{arrow} {r['code']}: {r['text']} {unit} ({pct})")
    lines += [""]
    if any(r["code"] == "GRAM ALTIN" for r in rows):
        lines.append("*Gram altın, ons altın (USD) ve USD/TRY kapanışları üzerinden hesaplanmıştır; "
                     "kuyumcu fiyatlarından farklılık gösterebilir.")
    lines += [
        f"Değerler ilgili piyasaların {dstr} günlük kapanışlarıdır; değişimler bir önceki işlem gününe göredir. "
        "Güncel kurlar için hikâyemize göz atın.",
        "",
        "Sizce bugün piyasaların yönünü ne belirleyecek?",
        "",
        config.DISCLAIMER,
        "",
        config.BRAND_TAG + " #Dolar #Altın #Borsa #Piyasalar",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------- Kart
def _background(size: tuple[int, int], seed: int) -> Image.Image:
    w, h = size
    bg = card.background_procedural(seed).resize((w, h), Image.LANCZOS).convert("RGBA")
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=card.NAVY + (170 + int(60 * y / h),))
    for x in range(0, w, 54):
        d.line([(x, 0), (x, h)], fill=(120, 170, 220, 14))
    for y in range(0, h, 54):
        d.line([(0, y), (w, y)], fill=(120, 170, 220, 14))
    return Image.alpha_composite(bg, ov)


def render_table(rows: list[dict], *, size: tuple[int, int], badge: str, title: str, subtitle: str,
                 stamp: str, note: str, src: str, top: int, bottom: int, seed: int,
                 show: int | None = None, right: int | None = None, background=None) -> Image.Image:
    """show: yalnızca ilk N satırı çiz (yerleşim tüm satırlara göre sabit kalır, animasyon için).
    right: sağ kenar boşluğu (Reels'te beğeni/yorum simgelerine yer bırakmak için)."""
    w, h = size
    xr = w - (M if right is None else right)
    img = background.copy() if background is not None else _background(size, seed)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    f_badge = card.font("SemiBold", 22)
    bw = card.spaced_width(d, badge, f_badge, 2.4) + 48
    d.rounded_rectangle((M, top, M + bw, top + 50), radius=25, fill=card.CYAN + (28,),
                        outline=card.CYAN + (220,), width=2)
    card.draw_spaced(d, (M + 24, top + 12), badge, f_badge, card.CYAN + (255,), 2.4)
    if stamp:
        f_date = card.font("Medium", 22)
        d.text((xr - d.textlength(stamp, font=f_date), top + 13), stamp, font=f_date, fill=card.GREY + (255,))

    y = top + 50 + 56
    f_title = card.font("ExtraBold", 84)
    for line in title.split("\n"):
        d.text((M, y), line, font=f_title, fill=card.WHITE + (255,))
        y += 98
    y += 12
    d.text((M, y), subtitle, font=card.font("SemiBold", 34), fill=card.CYAN + (255,))
    y += 66

    footer_y = h - bottom - 34
    n = len(rows)
    f_chg = card.font("Bold", 26)
    pill_w = max(d.textlength(tr_pct(r["change"]), font=f_chg) for r in rows) + 28   # hizalı sütun
    row_h = min(150, (footer_y - 90 - y) // max(n, 1))
    for i, r in enumerate(rows[:len(rows) if show is None else show]):
        t = y + i * row_h
        d.rounded_rectangle((M, t, xr, t + row_h - 14), radius=16, fill=card.PANEL + (210,),
                            outline=(120, 170, 220, 45), width=1)
        mid = t + (row_h - 14) // 2
        d.text((M + 28, mid - 30), r["code"], font=card.font("ExtraBold", 34), fill=card.WHITE + (255,))
        d.text((M + 28, mid + 10), r["name"], font=card.font("Medium", 20), fill=card.GREY + (255,))
        up, down = r["change"] > 0.005, r["change"] < -0.005
        color = card.GREEN if up else card.RED if down else card.GREY
        chg = tr_pct(r["change"])
        cw = d.textlength(chg, font=f_chg)
        pill = (xr - 28 - pill_w, mid - 22, xr - 28, mid + 22)
        d.rounded_rectangle(pill, radius=22, fill=color + (36,), outline=color + (150,), width=1)
        d.text((pill[2] - 14 - cw, mid - 16), chg, font=f_chg, fill=color + (255,))
        f_val = card._fit(d, r["text"], "ExtraBold", 46, 30, pill[0] - 40 - (M + 300))
        d.text((pill[0] - 28 - d.textlength(r["text"], font=f_val), mid - f_val.size * 0.62), r["text"],
               font=f_val, fill=card.WHITE + (255,))

    d.text((M, footer_y - 64), note, font=card.font("Medium", 19), fill=card.DIM + (255,))
    d.line([(M, footer_y - 26), (xr, footer_y - 26)], fill=(120, 170, 220, 60), width=1)
    d.rectangle((M, footer_y + 6, M + 12, footer_y + 18), fill=card.CYAN + (255,))
    card.draw_spaced(d, (M + 26, footer_y), config.SIGNATURE, card.font("Bold", 24), card.WHITE + (255,), 1.6)
    f_src = card.font("Medium", 20)
    d.text((xr - d.textlength(src, font=f_src), footer_y + 4), src, font=f_src, fill=card.DIM + (255,))
    return Image.alpha_composite(img, layer).convert("RGB")


# ------------------------------------------------------------------ Üst düzey
def _day_title(d: date) -> str:
    return f"{d.day} {card.TR_MONTHS[d.month - 1]} {TR_DAYS[d.weekday()]}"


def build_story(now: datetime) -> Image.Image | None:
    """09:00 hikâyesi: güncel kurlar (1080x1920). Instagram arayüzü üst ve alt ~250 pikseli kapatır."""
    weekend = now.weekday() >= 5
    rows = fetch_rows(weekend)
    if len(rows) < 4:
        log.warning("Kur hikâyesi için yeterli veri yok (%d satır).", len(rows))
        return None
    note = ("Kripto: 24 saatlik değişim · USD/TRY: cuma kapanışı" if weekend
            else "Döviz: günlük · Kripto: 24 saatlik · *Ons ve USD/TRY bazlı")
    return render_table(rows, size=(1080, 1920), badge="CANLI KUR · " + now.strftime("%H:%M"),
                        title="GÜNAYDIN", subtitle=_day_title(now.date()), stamp="",
                        note=note + " · Veriler gün içinde değişir", src="Yahoo Finance · CoinGecko",
                        top=260, bottom=270, seed=int(now.strftime("%Y%m%d")))


def close_day_for(now: datetime) -> date | None:
    """Salı-cumartesi sabahı: bir önceki günün kapanışı. Pazar/pazartesi: yeni kapanış yok."""
    if now.weekday() in (1, 2, 3, 4, 5):
        return now.date() - timedelta(days=1)
    return None


def build_close_post(now: datetime) -> tuple[dict, Image.Image] | None:
    day = close_day_for(now)
    if not day:
        return None
    rows = fetch_close_rows(day)
    if len(rows) < 4:
        log.warning("Kapanış özeti için yeterli veri yok (%d satır).", len(rows))
        return None
    image = render_table(rows, size=(W, H), badge="PİYASA KAPANIŞ ÖZETİ", title="DÜNÜ NASIL\nKAPATTIK?",
                         subtitle=_day_title(day) + " KAPANIŞI", stamp="",
                         note="Günlük kapanış değerleri · değişim bir önceki işlem gününe göre · *Ons bazlı",
                         src="Yahoo Finance", top=M, bottom=M, seed=int(now.strftime("%Y%m%d")) + 7)
    post = {
        "type": "rates",
        "category": "PİYASA KAPANIŞ ÖZETİ",
        "headline": f"DÜNÜ NASIL KAPATTIK · {_day_title(day)}",
        "rows": rows,
        "caption": build_close_caption(rows, day),
        "source_name": "Yahoo Finance",
        "source_link": "",
        "source_title": f"Kapanış özeti {day.isoformat()}",
        "close_day": day.isoformat(),
    }
    return post, image


# ------------------------------------------------------- Sessiz kapanış Reels'i
REEL_TOP, REEL_BOTTOM, REEL_RIGHT = 250, 430, 120   # Instagram arayüzünün kapattığı alanlar boş kalır
CLOSE_INTRO, CLOSE_STEP, CLOSE_HOLD, CLOSE_OUTRO = 1.2, 0.55, 5.0, 3.0


def _close_outro(base: Image.Image) -> Image.Image:
    img = Image.alpha_composite(base.convert("RGBA"), Image.new("RGBA", base.size, (4, 10, 20, 238)))
    d = ImageDraw.Draw(img)
    w, h = base.size
    cy = h // 2 - 240
    f = card.font("SemiBold", 42)
    for txt in ("Borsa haberleri için", "bizi takip edin"):
        d.text(((w - d.textlength(txt, font=f)) // 2, cy), txt, font=f, fill=card.GREY + (255,))
        cy += 60
    cy += 30
    fh = card.font("ExtraBold", 84)
    d.text(((w - d.textlength("@cryptos.cyp", font=fh)) // 2, cy), "@cryptos.cyp", font=fh,
           fill=card.WHITE + (255,))
    cy += 130
    cta = "Takip et  ·  Kaydet  ·  Paylaş"
    fc = card.font("Bold", 38)
    tw = d.textlength(cta, font=fc)
    d.rounded_rectangle(((w - tw) // 2 - 36, cy, (w + tw) // 2 + 36, cy + 84), radius=42,
                        fill=(14, 46, 62, 250), outline=card.CYAN + (255,), width=2)
    d.text(((w - tw) // 2, cy + 20), cta, font=fc, fill=card.CYAN + (255,))
    return img.convert("RGB")


def build_close_reel(rows: list[dict], day: date, now: datetime, out_path):
    """Kapanış tablosunun satırları tek tek beliren SESSİZ dikey videosu (ElevenLabs kredisi harcamaz).
    Döner: (video_yolu, kapak_görseli) ya da başarısızsa None."""
    import subprocess
    from pathlib import Path
    from . import reels

    ffmpeg = reels._ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg bulunamadı, kapanış Reels'i üretilemiyor.")
        return None
    size = (reels.VW, reels.VH)
    seed = int(now.strftime("%Y%m%d")) + 7
    bg = _background(size, seed)
    kw = dict(size=size, badge="PİYASA KAPANIŞ ÖZETİ", title="DÜNÜ NASIL\nKAPATTIK?",
              subtitle=_day_title(day) + " KAPANIŞI", stamp="",
              note="Günlük kapanış · değişim önceki işlem gününe göre · *Ons bazlı",
              src="Yahoo Finance", top=REEL_TOP, bottom=REEL_BOTTOM, right=REEL_RIGHT, seed=seed, background=bg)
    n = len(rows)
    stages = [render_table(rows, show=k, **kw) for k in range(n + 1)]
    outro = _close_outro(stages[-1])
    reveal_end = CLOSE_INTRO + n * CLOSE_STEP
    total = reveal_end + CLOSE_HOLD + CLOSE_OUTRO
    fade = 0.35

    def frame(t: float) -> Image.Image:
        if t >= reveal_end + CLOSE_HOLD:
            a = min(1.0, (t - reveal_end - CLOSE_HOLD) / fade)
            img = Image.blend(stages[-1], outro, a) if a < 1 else outro
        elif t < CLOSE_INTRO:
            img = stages[0]
        else:
            k = min(n, int((t - CLOSE_INTRO) / CLOSE_STEP) + 1)
            a = min(1.0, (t - CLOSE_INTRO - (k - 1) * CLOSE_STEP) / fade)
            img = Image.blend(stages[k - 1], stages[k], a) if a < 1 else stages[k]
        z = 1.0 + 0.03 * (t / total)            # hafif yakınlaşma: kare durağan görünmesin
        if z > 1.001:
            cw, ch = int(size[0] / z), int(size[1] / z)
            x0, y0 = (size[0] - cw) // 2, (size[1] - ch) // 2
            img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize(size, Image.BILINEAR)
        return img

    out_path = Path(out_path)
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(reels.FPS), "-i", "-",
           "-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-movflags", "+faststart", "-c:a", "aac", "-b:a", "64k", "-shortest", str(out_path)]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(int(total * reels.FPS)):
            proc.stdin.write(frame(i / reels.FPS).tobytes())
        proc.stdin.close()
        if proc.wait(timeout=300) != 0:
            raise RuntimeError(f"ffmpeg çıkış kodu {proc.returncode}")
    except Exception as exc:
        log.warning("Kapanış Reels'i üretilemedi: %s", exc)
        return None
    log.info("Kapanış Reels'i hazır: %s (%.1f sn, %.1f MB, sessiz)", out_path.name, total,
             out_path.stat().st_size / 1e6)
    return out_path, stages[-1]
