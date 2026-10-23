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
        post[k]["value"] = card.strip_emoji(post[k]["value"]).strip()
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


def prepare() -> int:
    history = load_history()
    news = [n for n in sources.fetch_news() if not is_repeat(n, history)]
    if len(news) < 3:
        log.info("Son %d saatte yeterli yeni haber yok, pencere 48 saate genişletiliyor.", config.NEWS_WINDOW_HOURS)
        news = [n for n in sources.fetch_news(48) if not is_repeat(n, history)]
    if not news:
        log.error("Yeni haber bulunamadı; bu çalışmada paylaşım yapılmayacak.")
        return 1
    news = news[:config.MAX_ITEMS_TO_MODEL]
    by_id = {n.id: n for n in news}
    market = sources.fetch_market_snapshot()
    recent = [h["headline"] for h in history[-8:]]

    llm = writer.Gemini()
    sel = writer.select_story(llm, "\n".join(n.for_prompt() for n in news), market, recent)
    log.info("Seçim: #%s (yedek #%s) — %s", sel["selected_id"], sel["runner_up_id"], sel["reason"])

    candidates = [by_id[i] for i in (sel["selected_id"], sel["runner_up_id"]) if i in by_id]
    if not candidates:
        candidates = news[:2]
    related_items = [by_id[i] for i in sel.get("related_ids", []) if i in by_id][:5]
    related = "\n".join(f"- ({r.source}) {r.title}: {r.summary[:400]}" for r in related_items)

    post = None
    for story in candidates:
        article = sources.fetch_article_text(story.link)
        source_text = "\n".join([story.title, story.summary, article, related, market])
        feedback = None
        for attempt in range(3):
            draft = normalize(writer.write_post(llm, story, article, related, market, feedback), story)
            errors = validate.check_post(draft, source_text)
            if not errors:
                post = draft
                break
            log.warning("Taslak %d kontrolden geçemedi: %s", attempt + 1, " | ".join(errors))
            feedback = errors
        if post:
            break
        log.warning("Haber atlanıyor, yedek habere geçiliyor: %s", story.title)
    if not post:
        log.error("Doğrulamadan geçen içerik üretilemedi; yanlış veri yayınlamamak için paylaşım iptal.")
        return 1

    now = datetime.now(TZ)
    stamp = now.strftime("%Y%m%d-%H%M")
    image = card.build_card(post, seed=int(now.timestamp()), when=now)
    config.POSTS_DIR.mkdir(exist_ok=True)
    config.OUTPUT_DIR.mkdir(exist_ok=True)
    img_rel = f"posts/{stamp}.jpg"
    image.save(config.ROOT / img_rel, "JPEG", quality=config.JPEG_QUALITY, optimize=True)

    post["image_path"] = img_rel
    post["created_at"] = now.isoformat()
    (config.OUTPUT_DIR / "post.json").write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.OUTPUT_DIR / "post.md").write_text(build_markdown(post), encoding="utf-8")
    (config.OUTPUT_DIR / "caption.txt").write_text(post["caption"], encoding="utf-8")
    _set_output("image_path", img_rel)
    log.info("Hazır: %s | %s", img_rel, post["headline"])
    print(build_markdown(post))
    return 0


def publish(image_url: str) -> int:
    from . import instagram

    post = json.loads((config.OUTPUT_DIR / "post.json").read_text(encoding="utf-8"))
    if os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"):
        log.info("DRY_RUN açık: Instagram'a gönderilmedi. Görsel: %s", image_url)
        return 0
    media_id = instagram.publish_image(image_url, post["caption"])
    history = load_history()
    history.append({"ts": datetime.now(timezone.utc).isoformat(), "link": post["source_link"],
                    "title": post["source_title"], "headline": post["headline"],
                    "image": post["image_path"], "media_id": media_id})
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
