"""@Cryptos.cyp otomatik piyasa istihbaratı paylaşım botu.

Kullanım:
  python -m bot.main prepare            # haberi seç, yaz, doğrula, kartı üret
  python -m bot.main publish URL        # hazırlanan içeriği Instagram'da yayınla
  python -m bot.main demo               # ağ bağlantısı olmadan örnek kart üret
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import card, config, sources, validate, writer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("bot")
TZ = ZoneInfo("Europe/Istanbul")


# ------------------------------------------------------------------ Geçmiş
def load_history() -> list[dict]:
    if config.HISTORY_FILE.exists():
        return json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def save_history(history: list[dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    history = [h for h in history if h["ts"] >= cutoff]
    config.STATE_DIR.mkdir(exist_ok=True)
    config.HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"\w+", s.lower()) if len(w) > 3}


def is_repeat(item: sources.NewsItem, history: list[dict]) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.HISTORY_DAYS)).isoformat()
    tw = _words(item.title)
    for h in history:
        if h["ts"] < cutoff:
            continue
        if item.link and item.link == h.get("link"):
            return True
        hw = _words(h.get("title", ""))
        if tw and hw and len(tw & hw) / len(tw | hw) > 0.5:
            return True
    return False


# ---------------------------------------------------------- Biçim düzeltmeleri
_STRAY = "'\"`’‘“”´"
_PCT_AFTER = re.compile(r"^([+\-−]?)\s*(\d[\d.,]*)\s*%\s*(\+?)$")      # -0,7%  -> −%0,7
_PCT_BEFORE = re.compile(r"^([+\-−]?)\s*%\s*([+\-−]?)\s*(\d[\d.,]*)\s*(\+?)$")  # %-0.7 -> −%0,7


def format_value(v: str) -> str:
    """Metrik değerini kart için temizler: fazladan işaretleri atar, yüzdeyi Türkçe biçime getirir."""
    v = card.strip_emoji(v)
    v = "".join(ch for ch in v if ch not in _STRAY).strip()
    m = _PCT_AFTER.match(v)
    if m:
        sign, num, plus = m.groups()
    else:
        m = _PCT_BEFORE.match(v)
        if not m:
            return "−" + v[1:] if v.startswith("-") else v
        sign, sign2, num, plus = m.groups()
        sign = sign or sign2
    if re.fullmatch(r"\d+\.\d{1,2}", num):     # 0.7 -> 0,7 (binlik ayırıcı değil, ondalık)
        num = num.replace(".", ",")
    sign = {"-": "−", "−": "−", "+": "+"}.get(sign, "")
    return f"{sign}%{num}{plus}"


TICKER_NAMES = {
    "NVDA": ["nvidia"], "TSM": ["tsmc", "taiwan semiconductor"], "ASML": ["asml"], "AMD": ["amd"],
    "INTC": ["intel"], "MU": ["micron"], "AVGO": ["broadcom"], "QCOM": ["qualcomm"], "ARM": ["arm holdings"],
    "MSFT": ["microsoft"], "GOOGL": ["alphabet", "google"], "AMZN": ["amazon"], "META": ["meta platforms"],
    "AAPL": ["apple"], "TSLA": ["tesla"], "ORCL": ["oracle"], "CRWV": ["coreweave"], "NBIS": ["nebius"],
    "IREN": ["iren"], "COIN": ["coinbase"], "MSTR": ["strategy", "microstrategy"], "HOOD": ["robinhood"],
    "IBIT": ["ibit", "ishares bitcoin"], "SOXL": ["soxl"], "BTC-USD": ["bitcoin", "btc"],
    "ETH-USD": ["ethereum", "ether", "eth"], "SOL-USD": ["solana"], "XRP-USD": ["xrp", "ripple"],
}


def ticker_is_relevant(ticker: str, text: str) -> bool:
    """Etiket yalnızca şirket/varlık haberin başlığında veya metninde geçiyorsa gösterilir."""
    t = (ticker or "").strip().upper()
    if not t:
        return False
    low = text.lower()
    names = TICKER_NAMES.get(t, []) + [t.removesuffix("-USD").lower()]
    return any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", low) for n in names)


# --------------------------------------------------------------- Metin çıktısı
def build_caption(post: dict) -> str:
    imp = post["impacts"]
    return "\n".join([
        post["hook"].strip(), "",
        post["context"].strip(), "",
        "PİYASA ETKİSİ",
        f"1. Kurumsal Oyuncular ve Likidite: {imp['institutional'].strip()}",
        f"2. Fiyat / Trend Dinamikleri: {imp['price'].strip()}",
        f"3. Küçük Yatırımcı İçin Risk/Fırsat Çerçevesi: {imp['retail'].strip()}", "",
        post["cta"].strip(), "",
        f"Kaynak: {post['source_name']}",
        config.DISCLAIMER, "",
        config.HASHTAGS,
    ])


def build_markdown(post: dict) -> str:
    """Sayfanın orijinal iki bloklu formatı (arşiv ve kontrol için)."""
    return f"""[BLOK 1: GÖRSEL KART BİLGİLERİ]
- KATEGORİ ROZETİ: {post['category']}
- MANŞET: {post['headline']}
- METRİK 1: 📊 {post['metric1']['label']}: {post['metric1']['value']}
- METRİK 2: 🔥 {post['metric2']['label']}: {post['metric2']['value']}
- ÖZET VE İÇGÖRÜ: {post['summary']}
- GÖRSEL ÜRETİM PROMPTU (İngilizce): {post['image_prompt']}
- İMZA: {config.SIGNATURE}

[BLOK 2: INSTAGRAM AÇIKLAMASI (CAPTION)]
{post['caption']}
"""


def normalize(post: dict, story: sources.NewsItem) -> dict:
    post["headline"] = card.tr_upper(card.strip_emoji(post["headline"]).strip().rstrip("."))
    post["category"] = card.strip_emoji(post["category"]).upper().strip()
    for k in ("metric1", "metric2"):
        post[k]["label"] = card.strip_emoji(post[k]["label"]).rstrip(":").strip()
        post[k]["value"] = format_value(post[k]["value"])
    post["source_name"] = story.source
    post["source_link"] = story.link
    post["source_title"] = story.title
    post["caption"] = build_caption(post)
    return post


# --------------------------------------------------------------------- Akış
def _set_output(key: str, value: str) -> None:
    gh = os.getenv("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def _save_outputs(post: dict, image, now: datetime, story_image=None) -> None:
    stamp = now.strftime("%Y%m%d-%H%M")
    config.POSTS_DIR.mkdir(exist_ok=True)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    img_rel = f"posts/{stamp}.jpg"
    image.save(config.ROOT / img_rel, "JPEG", quality=config.JPEG_QUALITY, optimize=True)
    images = [img_rel]
    post["image_path"] = img_rel
    if story_image is not None:
        story_rel = f"posts/{stamp}-story.jpg"
        story_image.save(config.ROOT / story_rel, "JPEG", quality=config.JPEG_QUALITY, optimize=True)
        post["story_image_path"] = story_rel
        images.append(story_rel)
    post["created_at"] = now.isoformat()
    (config.OUTPUT_DIR / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.OUTPUT_DIR / "caption.txt").write_text(post["caption"], encoding="utf-8")
    (config.OUTPUT_DIR / "images.txt").write_text("\n".join(images) + "\n", encoding="utf-8")
    if post.get("type") != "rates":
        (config.OUTPUT_DIR / "post.md").write_text(build_markdown(post), encoding="utf-8")
    _set_output("image_path", img_rel)
    log.info("Hazır: %s%s | %s", img_rel, " + hikâye" if story_image is not None else "", post["headline"])


def wants_rates(now: datetime) -> bool:
    """Günün ilk paylaşımı (09:00-09:59 TSİ) kur tablosudur. POST_MODE=kur/haber ile elle seçilebilir."""
    mode = os.getenv("POST_MODE", "").strip().lower()
    if mode in ("kur", "rates"):
        return True
    if mode in ("haber", "news"):
        return False
    return now.hour == 9


def prepare() -> int:
    """09:00: güncel kur HİKÂYESİ + (salı-cumartesi) dünün KAPANIŞ ÖZETİ gönderisi.
    Pazar/pazartesi sabahı ve diğer saatlerde gönderi olarak haber paylaşılır."""
    now = datetime.now(TZ)
    story_image = None
    if wants_rates(now):
        from . import rates
        try:
            story_image = rates.build_story(now)
        except Exception as exc:
            log.warning("Kur hikâyesi üretilemedi: %s", exc)
        try:
            built = rates.build_close_post(now)
        except Exception as exc:
            log.warning("Kapanış özeti üretilemedi: %s", exc)
            built = None
        if built:
            post, image = built
            _save_outputs(post, image, now, story_image)
            print(post["caption"])
            return 0
        log.info("Bu sabah kapanış özeti yok; gönderi olarak haber paylaşılacak.")
    built = build_news_post()
    if not built:
        if story_image is not None:
            log.error("Haber üretilemedi; yalnızca hikâye paylaşılamaz (gönderi gerekli).")
        return 1
    post, image = built
    _save_outputs(post, image, now, story_image)
    print(build_markdown(post))
    return 0


def build_news_post():
    history = load_history()
    news = [n for n in sources.fetch_news() if not is_repeat(n, history)]
    if len(news) < 3:
        log.info("Son %d saatte yeterli yeni haber yok, pencere 48 saate genişletiliyor.", config.NEWS_WINDOW_HOURS)
        news = [n for n in sources.fetch_news(48) if not is_repeat(n, history)]
    if not news:
        log.error("Yeni haber bulunamadı; bu çalışmada paylaşım yapılmayacak.")
        return None
    news = news[:config.MAX_ITEMS_TO_MODEL]
    by_id = {n.id: n for n in news}
    market = sources.fetch_market_snapshot()
    recent = [h["headline"] for h in history if h.get("type") != "rates"][-8:]

    llm = writer.Gemini()
    post = None
    excluded: set[int] = set()
    for round_no in range(2):  # ilk seçimdeki haberlerin metni okunamazsa bir kez yeniden seçilir
        pool = [n for n in news if n.id not in excluded]
        if not pool:
            break
        sel = writer.select_story(llm, "\n".join(n.for_prompt() for n in pool), market, recent)
        log.info("Seçim %d: #%s (yedek #%s) — %s", round_no + 1, sel["selected_id"], sel["runner_up_id"],
                 sel["reason"])
        candidates = [by_id[i] for i in (sel["selected_id"], sel["runner_up_id"])
                      if i in by_id and i not in excluded]
        if not candidates:
            candidates = pool[:2]
        related_items = [by_id[i] for i in sel.get("related_ids", []) if i in by_id][:5]
        related = "\n".join(f"- ({r.source}) {r.title}: {r.summary[:400]}" for r in related_items)

        for story in candidates:
            excluded.add(story.id)
            article = sources.fetch_article_text(story.link)
            if len(article) < config.MIN_ARTICLE_CHARS:
                # Ücretli/kapalı içerik: model yalnızca başlığı görür, ana rakamlara ulaşamaz.
                log.warning("Haber metni okunamadı (%d karakter, muhtemelen ücretli içerik), atlanıyor: %s",
                            len(article), story.title)
                continue
            source_text = "\n".join([story.title, story.summary, article, related, market])
            feedback = None
            for attempt in range(3):
                draft = normalize(writer.write_post(llm, story, article, related, market, feedback), story)
                errors = validate.check_post(draft, source_text)
                if not errors:
                    post = draft
                    story_text = f"{story.title} {story.summary} {article}"
                    break
                log.warning("Taslak %d kontrolden geçemedi: %s", attempt + 1, " | ".join(errors))
                feedback = errors
            if post:
                break
            log.warning("Haber atlanıyor, yedek habere geçiliyor: %s", story.title)
        if post:
            break
    if not post:
        log.error("Doğrulamadan geçen içerik üretilemedi; yanlış veri yayınlamamak için paylaşım iptal.")
        return None

    ticker = post.get("ticker", "")
    if ticker and not ticker_is_relevant(ticker, story_text):
        log.info("Borsa kodu %s haber metninde geçmiyor, etiket gösterilmeyecek.", ticker)
        ticker = ""
    post["quote"] = sources.fetch_quote(ticker) if ticker else None
    if post["quote"]:
        log.info("Borsa kodu etiketi: %s %+.2f%%", post["quote"]["symbol"], post["quote"]["change"])

    now = datetime.now(TZ)
    image = card.build_card(post, seed=int(now.timestamp()), when=now)
    return post, image


def publish(url: str) -> int:
    """url: görsellerin herkese açık klasör adresi ('/' ile biter) ya da doğrudan gönderi görseli."""
    from . import instagram

    post = json.loads((config.OUTPUT_DIR / "post.json").read_text(encoding="utf-8"))
    if url.endswith("/"):
        feed_url = url + Path(post["image_path"]).name
        story_url = url + Path(post["story_image_path"]).name if post.get("story_image_path") else None
    else:
        feed_url, story_url = url, None
    if os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"):
        log.info("DRY_RUN açık: Instagram'a gönderilmedi. Gönderi: %s | Hikâye: %s", feed_url, story_url)
        return 0
    if story_url:
        try:
            instagram.publish_story(story_url)
        except Exception as exc:  # hikâye başarısız olsa da gönderi yayınlanır
            log.warning("Hikâye yayınlanamadı: %s", exc)
    media_id = instagram.publish_image(feed_url, post["caption"])
    history = load_history()
    history.append({"ts": datetime.now(timezone.utc).isoformat(), "link": post["source_link"],
                    "title": post["source_title"], "headline": post["headline"],
                    "image": post["image_path"], "media_id": media_id, "type": post.get("type", "news")})
    save_history(history)
    return 0


def demo() -> int:
    """Ağsız örnek: kart tasarımını ve doğrulamayı yerelde görmek için."""
    story = sources.NewsItem(1, "CoinDesk", "Bitcoin ETFs snap four-day outflow streak with $523.4M inflows",
                             "US spot bitcoin ETFs recorded $523.4 million in net inflows on Thursday...",
                             "https://example.com", datetime.now(timezone.utc))
    post = {
        "category": "INSTITUTIONAL FLOWS & ETF",
        "headline": "Spot Bitcoin ETF'lerinde dört günlük çıkış serisi sona erdi",
        "metric1": {"label": "24 Saatlik Net Akış", "value": "+523,4 Milyon $"},
        "metric2": {"label": "Önceki 4 Günün Toplam Çıkışı", "value": "-1,18 Milyar $"},
        "summary": "IBIT öncülüğündeki girişler, dört seanslık çıkış baskısının ardından kurumsal talebin "
                   "yeniden güç kazandığına işaret ediyor. Akışların kalıcılığı, Fed beklentileri ve dolar "
                   "endeksindeki seyirle doğrudan ilişkili olacak.",
        "image_prompt": "abstract dark navy financial terminal, neon cyan data streams, no text",
        "hook": "Dört seans süren kurumsal çıkışın ardından ETF kanalında yön yeniden değişti.",
        "context": "ABD spot Bitcoin ETF'leri perşembe günü 523,4 milyon $ net giriş kaydetti. Önceki dört "
                   "seansta toplam çıkış 1,18 milyar $ seviyesindeydi.",
        "impacts": {"institutional": "Girişlerin büyük bölümü en likit fonlarda yoğunlaştı.",
                    "price": "Spot talep, kısa vadeli satış baskısını dengeleyen bir unsur olarak izleniyor.",
                    "retail": "Tek günlük akış veri trend teyidi değildir; serinin devamı izlenmeli."},
        "cta": "Sizce bu giriş kalıcı bir dönüşün başlangıcı mı, yoksa teknik bir tepki mi?",
    }
    post = normalize(post, story)
    print("Doğrulama:", validate.check_post(post, "523.4 million ... total outflows of $1.18 billion") or "geçti")
    now = datetime.now(TZ)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    img = card.render_card(post, card.background_procedural(42), now)
    img.save(config.OUTPUT_DIR / "demo_card.jpg", "JPEG", quality=config.JPEG_QUALITY)
    (config.OUTPUT_DIR / "demo_post.md").write_text(build_markdown(post), encoding="utf-8")
    print(build_markdown(post))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "prepare"
    if cmd == "prepare":
        sys.exit(prepare())
    if cmd == "publish":
        sys.exit(publish(sys.argv[2]))
    if cmd == "demo":
        sys.exit(demo())
    print(__doc__)
    sys.exit(2)
