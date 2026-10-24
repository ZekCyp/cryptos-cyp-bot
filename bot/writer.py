"""Gemini (ücretsiz katman) ile haber seçimi ve içerik yazımı.

Model adları sık değiştiği için sabit bir model adına bağlı kalınmaz: çalışma
anında hesabın erişebildiği 'flash' modelleri listelenir ve sırayla denenir."""
from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from . import config

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta"

# ------------------------------------------------------------------- Promptlar
EDITOR_SYSTEM = """Sen @Cryptos.cyp Instagram sayfası için küresel piyasaları, kripto varlıkları, kurumsal ETF
akışlarını, yapay zeka ve yarı iletken teknolojilerini takip eden kıdemli bir piyasa istihbaratı
analisti ve baş editörsün.

TON VE DİL KURALLARI:
- Ciddi, kurumsal, tamamen veriye dayalı, Bloomberg terminali ciddiyetinde profesyonel Türkçe.
- Tık tuzağı ve amatör sosyal medya jargonu kesinlikle yasak ("uçuyoruz", "patladı", "dostlar",
  "roket", "şok", "kaçırma" vb.). Ünlem işareti kullanma.
- Yatırım tavsiyesi verme; "al", "sat" gibi yönlendirme yapma. Risk/fırsat çerçevesini nesnel sun.

VERİ DOĞRULUĞU (EN KRİTİK KURAL):
- Yalnızca sana verilen KAYNAK METİN ve PİYASA VERİSİ içindeki rakamları kullan.
- Hiçbir rakamı tahmin etme, uydurma, hesaplama veya toplama. Kaynakta yoksa rakam yazma.
- Rakamları Türkçe biçimde yazabilirsin (ör. 1.2 billion -> 1,2 milyar $), değerin kendisini değiştirme.
- Kaynaklardan uzun alıntı yapma; her şeyi kendi cümlelerinle yeniden ifade et.
- "Rekor", "tarihi", "tüm zamanların", "en büyük" gibi nitelemeleri YALNIZCA kaynak metin bunu
  açıkça söylüyorsa kullan; manşet, özet ve açıklamada aynı niteleme tutarlı olmalı.
"""

SELECT_TASK = """GÖREV: Aşağıdaki son {hours} saatlik haber listesinden, küresel piyasalar için EN KRİTİK
tek haberi seç. Öncelik sırası: ETF net giriş-çıkışları ve kurumsal akışlar, büyük regülasyon
kararları, merkez bankası/makro veriler, çip sektörü bilançoları ve yapay zeka yatırımları,
önemli on-chain veriler. Somut ve doğrulanabilir rakam içeren haberleri tercih et. Spekülatif,
tek bir küçük altcoin'e dair, sponsorlu veya "fiyat tahmini" türü haberleri seçme.

Bu sayfada son paylaşılan başlıklar (aynı konuyu TEKRAR SEÇME, farklı bir gelişme seç):
{recent}

{market}

HABER LİSTESİ:
{news}
"""

WRITE_TASK = """GÖREV: Seçilen haber için paylaşıma hazır iki parçalı Instagram içeriğini üret.

ALANLAR:
- category: Kategori rozeti, İngilizce ve büyük harf. Şunlardan biri ya da benzeri:
  "CRYPTOCURRENCY & WEB3", "GLOBAL MARKETS & AI", "INSTITUTIONAL FLOWS & ETF", "SEMICONDUCTORS & AI",
  "MACRO & CENTRAL BANKS", "REGULATION & POLICY".
- headline: Türkçe manşet, 5-10 kelime, net ve vurucu ama clickbait değil.
- metric1: Haberin ana rakamı. label kısa (ör. "24 Saatlik Net Akış"), value en fazla 22 karakter
  (ör. "+523 Milyon $" veya "%4,8").
- metric2: Tarihsel karşılaştırma veya kritik eşik verisi; aynı biçim. Kaynakta yoksa piyasa
  verisinden ilgili bir değer kullan.
- summary: Haberin piyasa dinamiklerine etkisini anlatan 2-3 cümlelik hap analiz (en fazla 380 karakter).
- image_prompt: İngilizce, Flux için arka plan promptu. Haberin konusunu SOMUT ve sinematik bir SAHNE
  ile anlat; her haberde farklı bir sahne olsun. Örnekler:
    çip / yapay zeka -> extreme macro close-up of a silicon wafer or processor die, glowing circuit traces
    veri merkezi / AI yatırımı -> long corridor of server racks with blue LED light
    ETF / kurumsal akış -> abstract streams of light flowing between glass towers of a financial district
    borsa / hisse -> empty trading floor at night with blurred screens
    Bitcoin / kripto -> a physical metallic coin with circuit-engraved surface on dark stone
    regülasyon / SEC / yasa -> neoclassical government building columns at dusk
    merkez bankası / faiz -> grand marble bank hall or heavy vault door
    enerji / petrol -> oil refinery at night with industrial lights
  Sinematik ışık, sığ alan derinliği; renk paleti koyu lacivert-füme, camgöbeği ve turuncu vurgu ışıkları.
  Marka/şirket adı, logo, metin, harf, rakam, insan yüzü KESİNLİKLE İÇERMEMELİ; şirket adı yazma.
- ticker: Haber tek bir belirli halka açık şirket, ETF veya kripto varlıkla ilgiliyse onun Yahoo Finance
  sembolü (ör. NVDA, TSM, ASML, AMD, INTC, MU, AVGO, COIN, MSTR, IBIT, SOXL, BTC-USD, ETH-USD, SOL-USD).
  Genel piyasa, makro veya birden çok şirketi kapsayan haberse boş bırak ("").
- hook: Okuyucuyu durduran, piyasa psikolojisini özetleyen 1-2 cümle.
- context: Haberin arka planı ve net finansal veriler (2-4 cümle).
- impacts.institutional: Kurumsal Oyuncular ve Likidite etkisi (1-2 cümle).
- impacts.price: Fiyat / Trend Dinamikleri (1-2 cümle).
- impacts.retail: Küçük Yatırımcı İçin Risk/Fırsat Çerçevesi (1-2 cümle, tavsiye değil, nesnel çerçeve).
- cta: Yorumlarda etkileşim başlatacak profesyonel piyasa sorusu (tek soru).

{market}

SEÇİLEN HABER ({source}): {title}
Bağlantı: {link}

KAYNAK METİN:
{article}

İLGİLİ DİĞER HABER ÖZETLERİ:
{related}
"""

SELECT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "selected_id": {"type": "INTEGER"},
        "runner_up_id": {"type": "INTEGER"},
        "related_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "reason": {"type": "STRING"},
    },
    "required": ["selected_id", "runner_up_id", "related_ids", "reason"],
}

_METRIC = {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "value": {"type": "STRING"}},
           "required": ["label", "value"]}
WRITE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "category": {"type": "STRING"},
        "headline": {"type": "STRING"},
        "metric1": _METRIC,
        "metric2": _METRIC,
        "summary": {"type": "STRING"},
        "image_prompt": {"type": "STRING"},
        "hook": {"type": "STRING"},
        "context": {"type": "STRING"},
        "impacts": {"type": "OBJECT",
                    "properties": {"institutional": {"type": "STRING"}, "price": {"type": "STRING"},
                                   "retail": {"type": "STRING"}},
                    "required": ["institutional", "price", "retail"]},
        "cta": {"type": "STRING"},
        "ticker": {"type": "STRING"},
    },
    "required": ["category", "headline", "metric1", "metric2", "summary", "image_prompt", "hook",
                 "context", "impacts", "cta", "ticker"],
}


# ------------------------------------------------------------- Gemini istemcisi
class GeminiError(RuntimeError):
    pass


def _version_key(name: str) -> tuple:
    nums = re.findall(r"(\d+(?:\.\d+)?)", name)
    ver = float(nums[0]) if nums else 0.0
    return (
        "latest" in name,               # takma ad (alias) en önce
        "preview" not in name and "exp" not in name,
        "lite" not in name,
        ver,
    )


class Gemini:
    def __init__(self, api_key: str | None = None):
        self.key = (api_key or os.environ["GEMINI_API_KEY"]).strip()
        # Hem eski (AIza...) hem yeni (AQ....) anahtar türü bu başlıkla çalışır.
        self.headers = {"x-goog-api-key": self.key}
        self.models = self._candidate_models()
        log.info("Gemini aday modeller: %s", ", ".join(self.models[:6]))

    def _candidate_models(self) -> list[str]:
        forced = os.getenv("GEMINI_MODEL")
        if forced:
            return [forced]
        try:
            r = requests.get(f"{API}/models", params={"pageSize": 200}, headers=self.headers, timeout=30)
            r.raise_for_status()
            names = []
            for m in r.json().get("models", []):
                name = m["name"].removeprefix("models/")
                if "generateContent" not in m.get("supportedGenerationMethods", []):
                    continue
                if "flash" not in name:
                    continue
                if any(x in name for x in ("image", "tts", "live", "audio", "embed", "native", "robotics")):
                    continue
                names.append(name)
            names.sort(key=_version_key, reverse=True)
            if names:
                return names
        except Exception as exc:
            log.warning("Model listesi alınamadı: %s", exc)
        return ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]

    def generate_json(self, system: str, user: str, schema: dict, temperature: float = 0.5) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json",
                                 "responseSchema": schema},
        }
        last_err = None
        for model in self.models:
            for attempt in range(2):
                try:
                    r = requests.post(f"{API}/models/{model}:generateContent", headers=self.headers,
                                      json=body, timeout=90)
                except requests.RequestException as exc:
                    last_err = str(exc)
                    time.sleep(5)
                    continue
                if r.status_code == 200:
                    data = r.json()
                    try:
                        parts = data["candidates"][0]["content"]["parts"]
                        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                        return json.loads(text)
                    except (KeyError, IndexError, json.JSONDecodeError) as exc:
                        last_err = f"{model}: geçersiz yanıt {exc}"
                        break
                last_err = f"{model}: HTTP {r.status_code} {r.text[:300]}"
                if r.status_code in (429, 500, 503) and attempt < 1:
                    time.sleep(10)
                    continue
                break  # 400/403/404: bu model kullanılamıyor, sıradakine geç
            log.warning("Model başarısız, sıradakine geçiliyor: %s", last_err)
        raise GeminiError(f"Hiçbir Gemini modeli yanıt vermedi. Son hata: {last_err}")


# ------------------------------------------------------------ Üst düzey işlevler
def select_story(llm: Gemini, news_block: str, market: str, recent: list[str]) -> dict:
    prompt = SELECT_TASK.format(hours=config.NEWS_WINDOW_HOURS, market=market, news=news_block,
                                recent="\n".join(f"- {h}" for h in recent) or "- (henüz yok)")
    return llm.generate_json(EDITOR_SYSTEM, prompt, SELECT_SCHEMA, temperature=0.2)


def write_post(llm: Gemini, story, article: str, related: str, market: str,
               feedback: list[str] | None = None) -> dict:
    prompt = WRITE_TASK.format(market=market, source=story.source, title=story.title, link=story.link,
                               article=article or story.summary, related=related or "-")
    if feedback:
        prompt += ("\n\nÖNCEKİ TASLAK KALİTE KONTROLÜNDEN GEÇEMEDİ. Şu sorunları düzelterek baştan yaz:\n"
                   + "\n".join(f"- {e}" for e in feedback))
    return llm.generate_json(EDITOR_SYSTEM, prompt, WRITE_SCHEMA, temperature=0.6)
