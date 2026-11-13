"""Haberden 20-30 saniyelik, seslendirmeli ve altyazılı dikey Reels videosu (1080x1920, 30 fps).

Sahneler: KANCA (ilk karede hazır, büyük puntolu) → NE OLDU (manşet + metrikler) → NEDEN ÖNEMLİ (3 etki)
→ 30 GÜNLÜK GRAFİK → TAKİP ÇAĞRISI. Seslendirme varsa sahne süreleri sesle eşleşir; yoksa sabit sürelerle
sessiz üretilir. Altyazı her zaman vardır (çoğu kişi sessiz izler). Rakamlar doğrulanmış gönderiden ve
Yahoo Finance'ten gelir. Instagram arayüzünün kapattığı alanlar (üst ~220, alt ~400, sağ ~150 px) boş."""
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
VW, VH, FPS = 1080, 1920, 30
DEFAULT_DUR = {"hook": 2.8, "what": 5.5, "why": 8.0, "chart": 5.0, "outro": 3.2}
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
    def __init__(self, post: dict, background: Image.Image, chart: tuple | None,
                 scenes: list[tuple[str, str, float]]):
        """scenes: [(ad, altyazı metni, süre sn), ...]"""
        self.post, self.chart, self.scenes = post, chart, scenes
        self.total = sum(d for _, _, d in scenes)
        bg = _cover(background).filter(ImageFilter.GaussianBlur(6)).convert("RGBA")
        self.base = Image.alpha_composite(bg, Image.new("RGBA", (VW, VH), card.NAVY + (185,)))
        d = ImageDraw.Draw(self.base)
        for x in range(0, VW, 54):
            d.line([(x, 0), (x, VH)], fill=(120, 170, 220, 14))
        for y in range(0, VH, 54):
            d.line([(0, y), (VW, y)], fill=(120, 170, 220, 14))
        self.tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        reel = post.get("reel") or {}
        self.hook_text = card.tr_upper(card.strip_emoji(reel.get("hook_text") or post["headline"]))
        self.headline = card.tr_upper(card.strip_emoji(post["headline"]))
        self.sub_chunks = {name: self._chunks(text) for name, text, _ in scenes}

    def _chunks(self, text: str) -> list[str]:
        words = card.strip_emoji(text or "").split()
        out, cur = [], []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 34 or w.endswith((".", ",", "?", ";")) and len(cur) >= 3:
                out.append(" ".join(cur))
                cur = []
        if cur:
            out.append(" ".join(cur))
        return out

    def _scene_at(self, t: float) -> tuple[str, float, float]:
        start = 0.0
        for name, _, dur in self.scenes:
            if t < start + dur or name == self.scenes[-1][0]:
                return name, t - start, dur
            start += dur
        return self.scenes[-1][0], 0.0, self.scenes[-1][2]

    # -------------------------------------------------------------- tek kare
    def frame(self, t: float) -> Image.Image:
        layer = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        name, lt, dur = self._scene_at(t)

        # İlerleme çubuğu ve kategori rozeti (her karede)
        d.rounded_rectangle((L, TOP - 40, R, TOP - 34), radius=3, fill=(120, 170, 220, 50))
        d.rounded_rectangle((L, TOP - 40, L + int((R - L) * min(1, t / self.total)), TOP - 34), radius=3,
                            fill=card.CYAN + (255,))
        cat = card.strip_emoji(self.post["category"]).upper()
        f_badge = card.font("SemiBold", 24)
        bw = card.spaced_width(d, cat, f_badge, 2.4) + 48
        d.rounded_rectangle((L, TOP, L + bw, TOP + 52), radius=26, fill=card.CYAN + (30,),
                            outline=card.CYAN + (255,), width=2)
        card.draw_spaced(d, (L + 24, TOP + 13), cat, f_badge, card.CYAN + (255,), 2.4)

        enter = _phase(lt, 0, 0.3) if name != "hook" else 1.0       # kanca ilk karede hazır
        dx = int((1 - enter) * 60)
        getattr(self, f"_scene_{name}")(d, lt, dur, enter, dx)

        if name != "outro":
            self._subtitle(d, name, lt, dur)
        fy = BOTTOM + 10
        d.rectangle((L, fy + 6, L + 12, fy + 18), fill=card.CYAN + (255,))
        card.draw_spaced(d, (L + 26, fy), config.SIGNATURE, card.font("Bold", 24), card.WHITE + (255,), 1.6)
        return Image.alpha_composite(self.base, layer).convert("RGB")

    def _subtitle(self, d, name, lt, dur):
        chunks = self.sub_chunks.get(name) or []
        if not chunks:
            return
        idx = min(len(chunks) - 1, int(lt / max(dur - 0.25, 0.1) * len(chunks)))
        txt = chunks[idx]
        f = card.font("Bold", 38)
        lines = card.wrap(d, txt, f, R - L - 40)[:2]
        y = BOTTOM - 80 - 52 * (len(lines) - 1)
        for ln in lines:
            w = d.textlength(ln, font=f)
            x = L + (R - L - w) / 2
            d.rounded_rectangle((x - 16, y - 6, x + w + 16, y + 48), radius=10, fill=(0, 0, 0, 170))
            d.text((x, y), ln, font=f, fill=card.WHITE + (255,))
            y += 52

    # ---------------------------------------------------------------- sahneler
    def _block_top(self, height: int) -> int:
        """İçeriği rozet ile altyazı arasındaki alanda dikey ortalar."""
        area_top, area_bottom = TOP + 90, BOTTOM - 170
        return max(area_top, area_top + (area_bottom - area_top - height) // 2)

    def _scene_hook(self, d, lt, dur, enter, dx):
        # İlk kare = kapak karesi: her şey ilk karede tam ve DOĞRU değerle görünür (sayaç yok)
        for size in range(124, 64, -4):
            f = card.font("ExtraBold", size)
            lines = card.wrap(d, self.hook_text, f, R - L)
            if len(lines) <= 4:
                break
        val = card.strip_emoji(self.post["metric1"]["value"])
        f_val = card._fit(d, val, "ExtraBold", 130, 64, R - L)
        lh = int(f.size * 1.1)
        height = len(lines) * lh + 40 + f_val.size + 20 + 40
        y = self._block_top(height)
        for ln in lines:
            d.text((L, y), ln, font=f, fill=card.WHITE + (255,))
            y += lh
        y += 40
        glow = 0.75 + 0.25 * (0.5 + 0.5 * math.sin(lt * 4))
        d.text((L, y), val, font=f_val, fill=_alpha(card.CYAN, glow))
        y += f_val.size + 20
        d.text((L, y), card.strip_emoji(self.post["metric1"]["label"]), font=card.font("Medium", 36),
               fill=card.GREY + (255,))

    def _scene_what(self, d, lt, dur, enter, dx):
        for size in range(84, 52, -4):
            f = card.font("ExtraBold", size)
            lines = card.wrap(d, self.headline, f, R - L)
            if len(lines) <= 4:
                break
        lh = int(f.size * 1.1)
        y = self._block_top(len(lines) * lh + 40 + 2 * 190)
        for ln in lines:
            d.text((L + dx, y), ln, font=f, fill=_alpha(card.WHITE, enter))
            y += lh
        y += 40
        for idx, (key, accent) in enumerate((("metric1", card.CYAN), ("metric2", card.AMBER))):
            k = _phase(lt, 0.4 + idx * 0.4, 0.4)
            if k <= 0:
                continue
            d.rounded_rectangle((L, y, R, y + 170), radius=18, fill=card.PANEL + (int(225 * k),),
                                outline=_alpha(accent, 0.6 * k), width=2)
            d.text((L + 28, y + 24), card.strip_emoji(self.post[key]["label"]), font=card.font("Medium", 32),
                   fill=_alpha(card.GREY, k))
            val = card.strip_emoji(self.post[key]["value"])
            f_val = card._fit(d, val, "ExtraBold", 76, 40, R - L - 56)
            d.text((L + 28, y + 70), count_up(val, (lt - 0.4 - idx * 0.4) / 0.9), font=f_val,
                   fill=_alpha(accent, k))
            y += 190

    def _scene_why(self, d, lt, dur, enter, dx):
        imp = self.post["impacts"]
        items = [("01", imp["institutional"], card.CYAN), ("02", imp["price"], card.AMBER),
                 ("03", imp["retail"], card.GREEN)]
        for size in (36, 34, 32, 30):
            f_body = card.font("Regular", size)
            heights = [44 + len(card.wrap(d, card.strip_emoji(t), f_body, R - L - 110)[:4]) * int(size * 1.4) + 20
                       for _, t, _ in items]
            if 100 + sum(heights) <= BOTTOM - 170 - (TOP + 90):
                break
        y = self._block_top(100 + sum(heights))
        d.text((L + dx, y), "NEDEN ÖNEMLİ?", font=card.font("ExtraBold", 68), fill=_alpha(card.WHITE, enter))
        y += 100
        for i, (num, text, color) in enumerate(items):
            k = _phase(lt, i * dur / 3.2, 0.35)
            if k <= 0:
                break
            lines = card.wrap(d, card.strip_emoji(text), f_body, R - L - 110)[:4]
            lh = int(f_body.size * 1.4)
            h = 40 + len(lines) * lh
            d.rounded_rectangle((L, y, R, y + h), radius=16, fill=card.PANEL + (int(220 * k),),
                                outline=_alpha(color, 0.6 * k), width=2)
            d.text((L + 24, y + 20), num, font=card.font("ExtraBold", 32), fill=_alpha(color, k))
            ty = y + 20
            for ln in lines:
                d.text((L + 88, ty), ln, font=f_body, fill=(214, 222, 234, int(255 * k)))
                ty += lh
            y += h + 18

    def _scene_chart(self, d, lt, dur, enter, dx):
        series, name, unit = self.chart
        vals = [v for _, v in series]
        chg = (vals[-1] / vals[0] - 1) * 100
        color = card.GREEN if chg >= 0 else card.RED
        y = TOP + 110
        f_name = card._fit(d, card.tr_upper(name), "ExtraBold", 60, 36, R - L)
        d.text((L + dx, y), card.tr_upper(name), font=f_name, fill=_alpha(card.WHITE, enter))
        y += f_name.size + 20
        sign = "+" if chg >= 0 else "−"
        pct = f"{'▲' if chg >= 0 else '▼'} {sign}%{_tr_num(abs(chg), 1)}"
        d.text((L, y), pct, font=card.font("ExtraBold", 72), fill=_alpha(color, enter))
        d.text((L, y + 86), "son 30 gün", font=card.font("Medium", 30), fill=_alpha(card.GREY, enter))
        gy0, gy1 = y + 170, BOTTOM - 210
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.08 or hi * 0.01
        lo, hi = lo - pad, hi + pad
        d.rounded_rectangle((L, gy0 - 16, R, gy1 + 16), radius=16, fill=card.PANEL + (180,),
                            outline=(120, 170, 220, 45), width=1)
        n = max(2, int(len(vals) * _phase(lt, 0.2, dur * 0.7)))
        pts = [(L + 20 + (R - L - 40) * i / (len(vals) - 1), gy1 - (v - lo) / (hi - lo) * (gy1 - gy0))
               for i, v in enumerate(vals[:n])]
        d.line(pts, fill=color + (255,), width=6, joint="curve")
        x, yy = pts[-1]
        r = 9 + 3 * math.sin(lt * 6)
        d.ellipse((x - r, yy - r, x + r, yy + r), fill=color + (255,))

    def _scene_outro(self, d, lt, dur, enter, dx):
        k = enter
        cy = VH // 2 - 260
        for txt in ("Doğru borsa haberleri için", "bizi takip edin"):
            f = card.font("SemiBold", 42)
            tw = d.textlength(txt, font=f)
            d.text(((VW - tw) // 2, cy), txt, font=f, fill=_alpha(card.GREY, k))
            cy += 60
        cy += 30
        fh = card.font("ExtraBold", 84)
        tw = d.textlength("@cryptos.cyp", font=fh)
        d.text(((VW - tw) // 2, cy), "@cryptos.cyp", font=fh, fill=_alpha(card.WHITE, k))
        cy += 130
        cta = "Takip et  ·  Kaydet  ·  Paylaş"
        fc = card.font("Bold", 38)
        tw = d.textlength(cta, font=fc)
        d.rounded_rectangle(((VW - tw) // 2 - 36, cy, (VW + tw) // 2 + 36, cy + 84), radius=42,
                            fill=(14, 46, 62, int(250 * k)), outline=_alpha(card.CYAN, k), width=2)
        d.text(((VW - tw) // 2, cy + 20), cta, font=fc, fill=_alpha(card.CYAN, k))


def _cover(img: Image.Image) -> Image.Image:
    scale = max(VW / img.width, VH / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - VW) // 2, (img.height - VH) // 2
    return img.crop((left, top, left + VW, top + VH))


def chart_sentence(chart: tuple) -> str:
    series, name, _ = chart
    chg = (series[-1][1] / series[0][1] - 1) * 100
    verb = "yükseldi" if chg >= 0 else "geriledi"
    return f"{name} son 30 günde yüzde {_tr_num(abs(chg), 1)} {verb}."


def build_scenes(post: dict, chart: tuple | None) -> list[tuple[str, str]]:
    reel = post.get("reel") or {}
    scenes = [("hook", reel.get("hook") or post["headline"]),
              ("what", reel.get("what") or post["summary"]),
              ("why", reel.get("why") or post["impacts"]["price"])]
    if chart:
        scenes.append(("chart", chart_sentence(chart)))
    scenes.append(("outro", ""))
    return scenes


def _ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # GitHub sunucusunda ffmpeg yoksa pip paketiyle gelen sürüm kullanılır
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def render_video(post: dict, background: Image.Image, chart: tuple | None, out_path: Path,
                 voiced: bool = True) -> Path | None:
    """Kareleri doğrudan ffmpeg'e aktarır. Başarısız olursa None döner (gönderi kaydırmalı olarak çıkar)."""
    from . import voice

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        log.warning("ffmpeg bulunamadı, Reels üretilemiyor.")
        return None
    scene_texts = build_scenes(post, chart)
    # Kapanış sahnesi seslendirilmez (kredi tasarrufu); yalnızca ekranda görünür
    spoken = [config.REEL_OUTRO if n == "outro" else t for n, t in scene_texts]
    audio = voice.synthesize(spoken, ffmpeg, cache_last=True) if voiced else None
    if audio:
        wav, durs = audio
        durs = [max(d, 1.8) for d in durs]
        durs[-1] = max(durs[-1] + 0.6, DEFAULT_DUR["outro"])   # takip çağrısı ekranda biraz kalsın
    else:
        wav, durs = None, [DEFAULT_DUR[n] for n, _ in scene_texts]
    scenes = [(n, t, d) for (n, t), d in zip(scene_texts, durs)]
    total = sum(durs)
    wav_path = out_path.with_suffix(".wav")
    if wav:
        wav_path.write_bytes(wav)
        audio_in = ["-i", str(wav_path)]
    else:
        audio_in = ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    r = ReelRenderer(post, background, chart, scenes)
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{VW}x{VH}", "-r", str(FPS), "-i", "-", *audio_in,
           "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-movflags", "+faststart", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
           "-af", "apad", "-shortest", str(out_path)]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(int(total * FPS)):
            proc.stdin.write(r.frame(i / FPS).tobytes())
        proc.stdin.close()
        if proc.wait(timeout=300) != 0:
            raise RuntimeError(f"ffmpeg çıkış kodu {proc.returncode}")
    except Exception as exc:
        log.warning("Reels videosu üretilemedi: %s", exc)
        return None
    finally:
        wav_path.unlink(missing_ok=True)
    size_mb = out_path.stat().st_size / 1e6
    log.info("Reels videosu hazır: %s (%.1f sn, %.1f MB, %s)", out_path.name, total, size_mb,
             "sesli" if wav else "sessiz")
    if size_mb > 18:  # jsDelivr dosya sınırının altında kalsın
        log.warning("Video çok büyük (%.1f MB), Reels atlanıyor.", size_mb)
        return None
    return out_path


def _in_slots(now, spec: str) -> bool:
    for item in spec.split(","):
        if "-" not in item:
            continue
        day, hour = item.split("-", 1)
        if (day == "*" or int(day) == now.weekday()) and int(hour) == now.hour:
            return True
    return False


def is_voiced_slot(now) -> bool:
    return _in_slots(now, config.VOICED_SLOTS)


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
