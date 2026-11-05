"""Haber kartından 9 saniyelik dikey Reels videosu (1080x1920, 30 fps, H.264 + sessiz AAC).

Akış: manşet ilk yarım saniyede belirir (izleyiciyi ilk saniyede yakalamak için) → rakamlar sayarak
gelir → 30 günlük grafik çizilir → kapanışta "Takip et" çağrısı. Tüm rakamlar doğrulanmış gönderiden
ve Yahoo Finance'ten gelir; Gemini kullanılmaz. Instagram arayüzünün kapattığı alanlar (üst ~220 px,
alt ~380 px, sağ ~130 px) boş bırakılır."""
from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import card, config

log = logging.getLogger(__name__)
VW, VH, FPS, DUR = 1080, 1920, 30, 9.0
L, R = 72, 1080 - 150           # sağdaki beğeni/yorum simgelerine yer bırak
TOP, BOTTOM = 230, 1920 - 400

_NUM = re.compile(r"\d[\d.,]*\d|\d")


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _phase(t: float, start: float, length: float) -> float:
    return _ease((t - start) / length)


def _parse_tr(tok: str) -> tuple[float, int] | None:
    """'1.234,5' -> (1234.5, 1);  '523,4' -> (523.4, 1);  '115' -> (115, 0)"""
    if "," in tok:
        intpart, dec = tok.rsplit(",", 1)
        try:
            return float(intpart.replace(".", "") + "." + dec), len(dec)
        except ValueError:
            return None
    try:
        return float(tok.replace(".", "")), 0
    except ValueError:
        return None


def _tr_num(v: float, dec: int) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def count_up(value: str, progress: float) -> str:
    """Metrik metnindeki ilk sayıyı 0'dan gerçek değerine doğru sayar; biçimi korur."""
    m = _NUM.search(value)
    if not m or progress >= 1:
        return value
    parsed = _parse_tr(m.group(0))
    if not parsed:
        return value
    num, dec = parsed
    return value[:m.start()] + _tr_num(num * _ease(progress), dec) + value[m.end():]


def _alpha(color: tuple, a: float) -> tuple:
    return color + (int(255 * max(0.0, min(1.0, a))),)


class ReelRenderer:
    def __init__(self, post: dict, background: Image.Image, chart: tuple | None):
        self.post = post
        self.chart = chart
        bg = _cover(background).filter(ImageFilter.GaussianBlur(6)).convert("RGBA")
        ov = Image.new("RGBA", (VW, VH), card.NAVY + (175,))
        self.base = Image.alpha_composite(bg, ov)
        d = ImageDraw.Draw(self.base)
        for x in range(0, VW, 54):
            d.line([(x, 0), (x, VH)], fill=(120, 170, 220, 14))
        for y in range(0, VH, 54):
            d.line([(0, y), (VW, y)], fill=(120, 170, 220, 14))
        tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        self.headline = card.tr_upper(card.strip_emoji(post["headline"]))
        for size in range(84, 50, -4):
            self.f_head = card.font("ExtraBold", size)
            self.head_lines = card.wrap(tmp, self.headline, self.f_head, R - L)
            if len(self.head_lines) <= 5:
                break

    # -------------------------------------------------------------- tek kare
    def frame(self, t: float) -> Image.Image:
        layer = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        p = self.post

        # Kategori rozeti
        a = _phase(t, 0.0, 0.4)
        cat = card.strip_emoji(p["category"]).upper()
        f_badge = card.font("SemiBold", 24)
        bw = card.spaced_width(d, cat, f_badge, 2.4) + 48
        d.rounded_rectangle((L, TOP, L + bw, TOP + 52), radius=26, fill=_alpha(card.CYAN, 0.12 * a),
                            outline=_alpha(card.CYAN, a), width=2)
        card.draw_spaced(d, (L + 24, TOP + 13), cat, f_badge, _alpha(card.CYAN, a), 2.4)

        # Manşet: satır satır, aşağıdan kayarak
        y = TOP + 52 + 46
        lh = int(self.f_head.size * 1.1)
        for i, ln in enumerate(self.head_lines):
            k = _phase(t, 0.1 + i * 0.12, 0.45)
            d.text((L, y + (1 - k) * 40), ln, font=self.f_head, fill=_alpha(card.WHITE, k))
            y += lh
        y += 18
        bar = _phase(t, 0.6, 0.5)
        d.rectangle((L, y, L + int(120 * bar), y + 6), fill=card.CYAN + (255,))
        y += 46

        # Metrikler: sayarak
        for idx, (key, accent) in enumerate((("metric1", card.CYAN), ("metric2", card.AMBER))):
            k = _phase(t, 1.6 + idx * 0.35, 0.5)
            if k <= 0:
                continue
            box = (L, y, R, y + 150)
            d.rounded_rectangle(box, radius=18, fill=card.PANEL + (int(225 * k),),
                                outline=_alpha(accent, 0.55 * k), width=2)
            d.text((L + 28, y + 24), card.strip_emoji(p[key]["label"]), font=card.font("Medium", 28),
                   fill=_alpha(card.GREY, k))
            val = count_up(card.strip_emoji(p[key]["value"]), (t - 1.6 - idx * 0.35) / 1.4)
            f_val = card._fit(d, p[key]["value"], "ExtraBold", 64, 36, R - L - 56)
            d.text((L + 28, y + 66), val, font=f_val, fill=_alpha(accent, k))
            y += 170

        # Grafik (varsa) ya da özet
        y += 10
        if self.chart:
            self._chart(d, t, y)
        else:
            k = _phase(t, 4.0, 0.6)
            f_sum = card.font("Regular", 32)
            for ln in card.wrap(d, card.strip_emoji(p["summary"]), f_sum, R - L)[:6]:
                d.text((L, y), ln, font=f_sum, fill=(214, 222, 234, int(255 * k)))
                y += 46

        # Kapanış: takip çağrısı
        k = _phase(t, 7.1, 0.5)
        if k > 0:
            veil = Image.new("RGBA", (VW, VH), card.NAVY + (int(238 * k),))
            layer = Image.alpha_composite(layer, veil)
            d = ImageDraw.Draw(layer)
            cy = VH // 2 - 200
            for txt, fnt, col in (("Günün kritik piyasa gelişmeleri", card.font("SemiBold", 40), card.GREY),
                                  ("veriyle, her gün", card.font("SemiBold", 40), card.GREY)):
                tw = d.textlength(txt, font=fnt)
                d.text(((VW - tw) // 2, cy), txt, font=fnt, fill=_alpha(col, k))
                cy += 58
            cy += 30
            handle = "@cryptos.cyp"
            fh = card.font("ExtraBold", 76)
            tw = d.textlength(handle, font=fh)
            d.text(((VW - tw) // 2, cy), handle, font=fh, fill=_alpha(card.WHITE, k))
            cy += 120
            cta = "Takip et  ·  Kaydet  ·  Paylaş"
            fc = card.font("Bold", 36)
            tw = d.textlength(cta, font=fc)
            d.rounded_rectangle(((VW - tw) // 2 - 36, cy, (VW + tw) // 2 + 36, cy + 80), radius=40,
                                fill=(14, 46, 62, int(250 * k)), outline=_alpha(card.CYAN, k), width=2)
            d.text(((VW - tw) // 2, cy + 20), cta, font=fc, fill=_alpha(card.CYAN, k))

        # İmza (her karede)
        fy = BOTTOM - 10
        d.rectangle((L, fy + 6, L + 12, fy + 18), fill=card.CYAN + (255,))
        card.draw_spaced(d, (L + 26, fy), config.SIGNATURE, card.font("Bold", 24), card.WHITE + (255,), 1.6)
        return Image.alpha_composite(self.base, layer).convert("RGB")

    def _chart(self, d: ImageDraw.ImageDraw, t: float, y: int) -> None:
        series, name, unit = self.chart
        k = _phase(t, 3.4, 0.4)
        if k <= 0:
            return
        vals = [v for _, v in series]
        first, last = vals[0], vals[-1]
        chg = (last / first - 1) * 100
        color = card.GREEN if chg >= 0 else card.RED
        d.text((L, y), f"{card.tr_upper(name)} · 30 GÜN", font=card.font("SemiBold", 26),
               fill=_alpha(card.GREY, k))
        sign = "+" if chg >= 0 else "−"
        pct = f"{'▲' if chg >= 0 else '▼'} {sign}%{_tr_num(abs(chg), 2)}"
        f_pct = card.font("ExtraBold", 40)
        d.text((R - d.textlength(pct, font=f_pct), y - 8), pct, font=f_pct, fill=_alpha(color, k))
        gy0, gy1 = y + 70, BOTTOM - 60
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.08 or hi * 0.01
        lo, hi = lo - pad, hi + pad
        d.rounded_rectangle((L, gy0 - 16, R, gy1 + 16), radius=16, fill=card.PANEL + (int(180 * k),),
                            outline=(120, 170, 220, int(45 * k)), width=1)
        draw_p = _phase(t, 3.7, 2.6)
        n = max(2, int(len(vals) * draw_p))
        pts = [(L + 20 + (R - L - 40) * i / (len(vals) - 1), gy1 - (v - lo) / (hi - lo) * (gy1 - gy0))
               for i, v in enumerate(vals[:n])]
        if len(pts) >= 2:
            d.line(pts, fill=_alpha(color, k), width=6, joint="curve")
            x, yy = pts[-1]
            r = 9 + 3 * math.sin(t * 6)
            d.ellipse((x - r, yy - r, x + r, yy + r), fill=_alpha(color, k))


def _cover(img: Image.Image) -> Image.Image:
    scale = max(VW / img.width, VH / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - VW) // 2, (img.height - VH) // 2
    return img.crop((left, top, left + VW, top + VH))


def render_video(post: dict, background: Image.Image, chart: tuple | None, out_path: Path) -> Path | None:
    """Kareleri doğrudan ffmpeg'e aktarır. Başarısız olursa None döner (gönderi kaydırmalı olarak çıkar)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:  # GitHub sunucusunda ffmpeg yoksa pip paketiyle gelen sürüm kullanılır
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg = None
    if not ffmpeg:
        log.warning("ffmpeg bulunamadı, Reels üretilemiyor.")
        return None
    r = ReelRenderer(post, background, chart)
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "-",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
           "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "96k",
           str(out_path)]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(int(DUR * FPS)):
            proc.stdin.write(r.frame(i / FPS).tobytes())
        proc.stdin.close()
        if proc.wait(timeout=180) != 0:
            raise RuntimeError(f"ffmpeg çıkış kodu {proc.returncode}")
    except Exception as exc:
        log.warning("Reels videosu üretilemedi: %s", exc)
        return None
    size_mb = out_path.stat().st_size / 1e6
    log.info("Reels videosu hazır: %s (%.1f MB)", out_path.name, size_mb)
    if size_mb > 18:  # jsDelivr dosya sınırının altında kalsın
        log.warning("Video çok büyük (%.1f MB), Reels atlanıyor.", size_mb)
        return None
    return out_path


def is_reel_slot(now) -> bool:
    """Varsayılan: pazartesi, çarşamba, cuma 18:00 paylaşımı Reels olarak çıkar. POST_FORMAT=reels ile elle."""
    import os
    forced = os.getenv("POST_FORMAT", "").strip().lower()
    if forced in ("reels", "reel"):
        return True
    if forced in ("carousel", "kaydirmali", "gonderi"):
        return False
    slots = {tuple(int(x) for x in s.split("-")) for s in config.REELS_SLOTS.split(",") if "-" in s}
    return (now.weekday(), now.hour) in slots
