"""Geçici tanı betiği: aday Türkçe RSS kaynaklarını ve makale metni okunabilirliğini test eder."""
import json, sys
from datetime import datetime, timezone
sys.path.insert(0, ".")
import feedparser
from bot import sources

CANDIDATES = {
    "AA Ekonomi": "https://www.aa.com.tr/tr/rss/default?cat=ekonomi",
    "Bloomberg HT": "https://www.bloomberght.com/rss",
    "NTV Ekonomi": "https://www.ntv.com.tr/ekonomi.rss",
    "TRT Haber Ekonomi": "https://www.trthaber.com/ekonomi_articles.rss",
    "Habertürk Ekonomi": "https://www.haberturk.com/rss/ekonomi.xml",
    "Investing TR": "https://tr.investing.com/rss/news.rss",
    "Dünya": "https://www.dunya.com/rss?dunya",
    "Ekonomim": "https://www.ekonomim.com/export/rss",
    "Para Analiz": "https://www.paraanaliz.com/feed/",
    "CoinTürk": "https://coin-turk.com/feed",
    "Kriptokoin": "https://kriptokoin.com/feed/",
    "BloombergHT Piyasalar": "https://www.bloomberght.com/rss/piyasalar",
}
out = {"checked_at": datetime.now(timezone.utc).isoformat(), "feeds": {}}
for name, url in CANDIDATES.items():
    r = {"url": url}
    try:
        resp = sources.SESSION.get(url, timeout=25)
        r["http"] = resp.status_code
        feed = feedparser.parse(resp.content)
        r["items"] = len(feed.entries)
        if feed.entries:
            e = feed.entries[0]
            r["first_title"] = e.get("title", "")[:120]
            r["has_date"] = bool(e.get("published_parsed") or e.get("updated_parsed"))
            r["summary_len"] = len(sources.clean_text(e.get("summary", "")))
            r["article_chars"] = len(sources.fetch_article_text(e.get("link", "")))
    except Exception as exc:
        r["error"] = str(exc)[:200]
    out["feeds"][name] = r
    print(name, r)
for sym in ("USDTRY=X", "EURTRY=X", "XU100.IS", "GC=F", "BTC-TRY"):
    try:
        out.setdefault("quotes", {})[sym] = sources.fetch_quote(sym)
    except Exception as exc:
        out.setdefault("quotes", {})[sym] = str(exc)
open("state/feed_status.json", "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=2))
