"""Yayın öncesi otomatik kalite kontrolü.

Sistem insan onayı olmadan yayın yaptığı için en kritik güvence buradadır:
metindeki her anlamlı sayı, kaynak metinde (haber + piyasa verisi) karşılığı
olan bir değer olmak zorundadır. Karşılığı yoksa içerik yayınlanmaz."""
from __future__ import annotations

import re

BANNED = [
    "uçuyoruz", "uçuş", "patladı", "patlama yaptı", "dostlar", "arkadaşlar", "roket", "to the moon",
    "moon", "kaçırma", "şok", "inanılmaz", "bomba", "çakıldı", "efsane", "çılgın", "ateş aldı",
    "garanti", "kesin kazanç", "zengin ol", "fırsatı kaçırmayın", "lambo",
]

_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def _candidates(token: str) -> set[float]:
    """Bir sayı dizgesini hem Türkçe (1.234,5) hem İngilizce (1,234.5) okumayla yorumla."""
    out: set[float] = set()
    for conv in (token.replace(".", "").replace(",", "."),        # Türkçe
                 token.replace(",", ""),                            # İngilizce
                 token.replace(",", ".")):                          # ondalık virgül, binlik yok
        try:
            out.add(abs(float(conv)))
        except ValueError:
            pass
    return out


def _numbers_with_context(text: str):
    for m in _NUM_RE.finditer(text):
        tok = m.group(0).strip(".,")
        if not tok:
            continue
        before = text[max(0, m.start() - 2):m.start()]
        after = text[m.end():m.end() + 12].lower()
        yield tok, before, after


def _is_trivial(tok: str, before: str, after: str) -> bool:
    """Tarih, yıl, madde numarası gibi doğrulama gerektirmeyen sayılar."""
    vals = _candidates(tok)
    if not vals:
        return True
    v = max(vals)
    is_int = re.fullmatch(r"\d+", tok) is not None
    pct_or_money = "%" in before or after.startswith(("%", " %", "$", " $", " milyon", " milyar",
                                                      " trilyon", " bin", " usd", " dolar", " bps"))
    if is_int and 1990 <= v <= 2035 and not pct_or_money:
        return True                                  # yıl
    if is_int and v <= 31 and not pct_or_money:
        return True                                  # gün, saat, madde no
    if after.startswith((" saat", " gün", " hafta", " ay ", " ay'", " yıl", "/7", " ekim", " kasım",
                         " aralık", " ocak", " şubat", " mart", " nisan", " mayıs", " haziran",
                         " temmuz", " ağustos", " eylül")):
        return True
    return False


def source_values(source_text: str) -> set[float]:
    vals: set[float] = set()
    for tok, _, _ in _numbers_with_context(source_text):
        vals |= _candidates(tok)
    return vals


def _matches(value: float, pool: set[float]) -> bool:
    for s in pool:
        for scale in (1, 1e3, 1e-3, 1e6, 1e-6, 1e9, 1e-9):
            ref = s * scale
            if ref == 0:
                if value == 0:
                    return True
                continue
            if abs(value - ref) / abs(ref) <= 0.012:   # yuvarlama payı (%1,2)
                return True
    return False


def unverified_numbers(generated: str, source_text: str) -> list[str]:
    pool = source_values(source_text)
    bad = []
    for tok, before, after in _numbers_with_context(generated):
        if _is_trivial(tok, before, after):
            continue
        if not any(_matches(v, pool) for v in _candidates(tok)):
            bad.append(tok)
    return sorted(set(bad))


def banned_phrases(text: str) -> list[str]:
    low = text.lower()
    return [w for w in BANNED if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low)]


def check_post(post: dict, source_text: str) -> list[str]:
    """Hata listesi döner; boş liste = yayına uygun."""
    errors: list[str] = []
    words = post["headline"].split()
    if not 4 <= len(words) <= 10:
        errors.append(f"Manşet {len(words)} kelime; 4-10 kelime olmalı.")
    if len(post["summary"]) > 420:
        errors.append("Özet çok uzun (en fazla 3 cümle, ~400 karakter).")
    for k in ("metric1", "metric2"):
        if len(post[k]["value"]) > 26:
            errors.append(f"{k} değeri kartta sığmayacak kadar uzun (en fazla 26 karakter).")

    text_fields = " \n".join([
        post["headline"], post["metric1"]["label"], post["metric1"]["value"],
        post["metric2"]["label"], post["metric2"]["value"], post["summary"], post["hook"],
        post["context"], *post["impacts"].values(), post["cta"],
    ])
    bad_nums = unverified_numbers(text_fields, source_text)
    if bad_nums:
        errors.append("Kaynakta karşılığı bulunmayan sayılar: " + ", ".join(bad_nums)
                      + ". Yalnızca kaynak metindeki değerleri kullan; hesaplama veya tahmin yapma.")
    bad_words = banned_phrases(text_fields)
    if bad_words:
        errors.append("Yasaklı/amatör ifadeler: " + ", ".join(bad_words))
    if len(post.get("caption", "")) > 2150:
        errors.append("Instagram açıklaması 2200 karakter sınırını aşıyor.")
    return errors
