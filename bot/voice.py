"""ElevenLabs ile Türkçe seslendirme.

Her sahne ayrı seslendirilir; böylece videodaki sahne süreleri sesle birebir eşleşir.
Rakamlar seslendirmeden önce Türkçe okunuşa çevrilir ("%23,9" -> "yüzde yirmi üç virgül dokuz").
Anahtar yoksa veya servis yanıt vermezse None döner ve video sessiz üretilir."""
from __future__ import annotations

import hashlib
import io
import logging
import re
import subprocess
import wave

import requests

from . import config

log = logging.getLogger(__name__)
RATE = 44100

# ---------------------------------------------------------- Türkçe sayı okunuşu
_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon"), (1000, "bin")]


def _under_thousand(n: int) -> str:
    h, rest = divmod(n, 100)
    t, o = divmod(rest, 10)
    parts = []
    if h:
        parts.append("yüz" if h == 1 else f"{_ONES[h]} yüz")
    if t:
        parts.append(_TENS[t])
    if o:
        parts.append(_ONES[o])
    return " ".join(parts)


def int_to_tr(n: int) -> str:
    if n == 0:
        return "sıfır"
    parts = []
    for value, name in _SCALES:
        q, n = divmod(n, value)
        if q:
            parts.append(name if (q == 1 and name == "bin") else f"{int_to_tr(q)} {name}")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def number_to_tr(tok: str) -> str:
    """'1.234,56' -> 'bin iki yüz otuz dört virgül elli altı'.  '0,05' -> 'sıfır virgül sıfır beş'"""
    if "," in tok:
        intpart, dec = tok.rsplit(",", 1)
    else:
        intpart, dec = tok, ""
    intpart = intpart.replace(".", "")
    if not intpart.isdigit() or (dec and not dec.isdigit()):
        return tok
    out = int_to_tr(int(intpart))
    if dec:
        lead = len(dec) - len(dec.lstrip("0"))
        dec_words = " ".join(["sıfır"] * lead + ([int_to_tr(int(dec))] if dec.strip("0") else []))
        out += " virgül " + dec_words
    return out


_REPL = [
    (r"(\d)\s*\$", r"\1 dolar"), (r"\$\s*(\d[\d.,]*)", r"\1 dolar"),
    (r"\b(bin|milyon|milyar|trilyon)\s*\$", r"\1 dolar"), (r"\b(bin|milyon|milyar|trilyon)\s*€", r"\1 euro"),
    (r"(\d)\s*€", r"\1 euro"), (r"€\s*(\d[\d.,]*)", r"\1 euro"),
    (r"(\d)\s*TL\b", r"\1 lira"),
    (r"[−–-]\s*%\s*(\d)", r"eksi yüzde \1"), (r"\+\s*%\s*(\d)", r"artı yüzde \1"), (r"%\s*(\d)", r"yüzde \1"),
    (r"(\d[\d.,]*)\s*%", r"yüzde \1"),
    (r"(?<![\w])[−–]\s*(\d)", r"eksi \1"),
]

def speakable(text: str) -> str:
    t = text.replace(" ", " ")
    for pat, rep in _REPL:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\d[\d.,]*\d|\d", lambda m: number_to_tr(m.group(0).rstrip(".,")) + m.group(0)[len(m.group(0).rstrip(".,")):], t)
    t = re.sub(r"\bETF('?\w*)", lambda m: "e te fe" + m.group(1), t)
    for word, spoken in (("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("AI", "yapay zeka")):
        t = re.sub(rf"\b{word}\b", spoken, t)
    return re.sub(r"\s+", " ", t).strip()


# ----------------------------------------------------------- ElevenLabs çağrısı
def _tts_mp3(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"
    body = {"text": text, "model_id": config.ELEVENLABS_MODEL,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.15,
                               "use_speaker_boost": True}}
    if "v2_5" in config.ELEVENLABS_MODEL or "flash" in config.ELEVENLABS_MODEL:
        body["language_code"] = "tr"
    r = requests.post(url, params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": config.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
                      json=body, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")
    return r.content


def _mp3_to_pcm(mp3: bytes, ffmpeg: str) -> bytes:
    proc = subprocess.run([ffmpeg, "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                           "-ar", str(RATE), "pipe:1"], input=mp3, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode()[:300])
    return proc.stdout


def _cached_mp3(text: str) -> bytes:
    """Her seferinde aynı olan metinler (ör. kapanış cümlesi) yalnızca bir kez seslendirilir;
    ses dosyası state/ klasöründe saklanır ve sonraki videolarda kredi harcanmaz."""
    key = hashlib.sha1(f"{config.ELEVENLABS_VOICE_ID}|{config.ELEVENLABS_MODEL}|{text}".encode()).hexdigest()[:12]
    path = config.STATE_DIR / f"tts-{key}.mp3"
    if path.exists():
        log.info("Kapanış seslendirmesi önbellekten alındı (kredi harcanmadı).")
        return path.read_bytes()
    data = _tts_mp3(text)
    config.STATE_DIR.mkdir(exist_ok=True)
    path.write_bytes(data)
    return data


def synthesize(segments: list[str], ffmpeg: str, gap: float = 0.25,
               cache_last: bool = False) -> tuple[bytes, list[float]] | None:
    """Sahne metinlerini seslendirir. (tek parça WAV, her sahnenin süresi) döner.
    cache_last: son sahne (kapanış cümlesi) önbellekten kullanılır."""
    if not (config.ELEVENLABS_API_KEY and config.ELEVENLABS_VOICE_ID):
        log.info("ElevenLabs anahtarı/ses kimliği yok, Reels sessiz üretilecek.")
        return None
    pcm, durations, charged = b"", [], 0
    silence = b"\x00\x00" * int(RATE * gap)
    try:
        for i, seg in enumerate(segments):
            spoken = speakable(seg)
            if cache_last and i == len(segments) - 1:
                mp3 = _cached_mp3(spoken)
            else:
                mp3 = _tts_mp3(spoken)
                charged += len(spoken)
            data = _mp3_to_pcm(mp3, ffmpeg) + silence
            pcm += data
            durations.append(len(data) / 2 / RATE)
    except Exception as exc:
        log.warning("Seslendirme başarısız, Reels sessiz üretilecek: %s", exc)
        return None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    log.info("Seslendirme hazır: %.1f sn, yaklaşık %d kredi (ElevenLabs).", sum(durations), charged)
    return buf.getvalue(), durations
