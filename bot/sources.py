"""Haber ve piyasa verisi toplama. Tüm kaynaklar ücretsiz ve anahtarsızdır.
Her kaynak bağımsızdır: biri hata verirse diğerleriyle devam edilir."""
from __future__ import annotations

import calendar
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import feedparser
import requests

from . import config

log = logging.getLogger(__name__)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    return _WS_RE.sub(" ", text).strip()


@dataclass
class NewsItem:
    id: int
    source: str
    title: str
    summary: str
    link: str
    published: datetime
    full_text: str = field(default="", repr=False)

    def for_prompt(self) -> str:
        age_h = (datetime.now(timezone.utc) - self.published).total_seconds() / 3600
        return (f"[{self.id}] ({self.source}, {age_h:.0f} saat önce) {self.title}\n"
                f"    {self.summary[:420]}")


# --------------------------------------------------------------------------- RSS
def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def fetch_news(window_hours: int = config.NEWS_WINDOW_HOURS) -> list[NewsItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    items: list[NewsItem] = []
    seen_titles: set[str] = set()
    for source, url in config.FEEDS.items():
        try:
            resp = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as exc:  # kaynak düşerse diğerlerine devam
            log.warning("RSS alınamadı: %s (%s)", source, exc)
            continue
        count = 0
        for entry in feed.entries[:40]:
            published = _entry_time(entry)
            if not published or published < cutoff:
                continue
            title = clean_text(entry.get("title", ""))
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or key in seen_titles:
                continue
            seen_titles.add(key)
            summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
            items.append(NewsItem(0, source, title, summary, entry.get("link", ""), published))
            count += 1
            if count >= config.FEED_LIMITS.get(source, 999):
                break
        log.info("RSS %-18s %d haber", source, count)
    items.sort(key=lambda n: n.published, reverse=True)
    for i, item in enumerate(items, start=1):
        item.id = i
    return items


# ------------------------------------------------------------ Makale tam metni
class _ParagraphParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth_skip = 0
        self.in_p = False
        self.buf: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "aside"):
            self.depth_skip += 1
        elif tag in ("p", "li", "h2") and not self.depth_skip:
            self.in_p, self.buf = True, []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "aside") and self.depth_skip:
            self.depth_skip -= 1
        elif tag in ("p", "li", "h2") and self.in_p:
            text = _WS_RE.sub(" ", "".join(self.buf)).strip()
            if len(text) > 60:
                self.paragraphs.append(text)
            self.in_p = False

    def handle_data(self, data):
        if self.in_p and not self.depth_skip:
            self.buf.append(data)


def fetch_article_text(url: str, limit: int = 7000) -> str:
    if not url:
        return ""
    try:
        resp = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
        resp.raise_for_status()
        parser = _ParagraphParser()
        parser.feed(resp.text)
        return "\n".join(parser.paragraphs)[:limit]
    except Exception as exc:
        log.warning("Makale metni alınamadı (%s): %s", url, exc)
        return ""


# -------------------------------------------------------------- Piyasa verisi
def _coingecko() -> list[str]:
    lines = []
    url = ("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,ripple"
           "&vs_currencies=usd&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true")
    data = SESSION.get(url, timeout=config.HTTP_TIMEOUT).json()
    names = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP"}
    for cid, sym in names.items():
        d = data.get(cid)
        if not d:
            continue
        lines.append(f"{sym} fiyat: {d['usd']:,.2f} USD | 24s değişim: {d.get('usd_24h_change', 0):+.2f}% | "
                     f"piyasa değeri: {d.get('usd_market_cap', 0)/1e9:,.1f} milyar USD | "
                     f"24s hacim: {d.get('usd_24h_vol', 0)/1e9:,.1f} milyar USD")
    g = SESSION.get("https://api.coingecko.com/api/v3/global", timeout=config.HTTP_TIMEOUT).json()["data"]
    lines.append(f"Toplam kripto piyasa değeri: {g['total_market_cap']['usd']/1e12:,.2f} trilyon USD | "
                 f"24s değişim: {g.get('market_cap_change_percentage_24h_usd', 0):+.2f}% | "
                 f"BTC dominansı: {g['market_cap_percentage']['btc']:.2f}%")
    return lines


def _fear_greed() -> list[str]:
    data = SESSION.get("https://api.alternative.me/fng/?limit=2", timeout=config.HTTP_TIMEOUT).json()["data"]
    today, prev = data[0], data[1]
    return [f"Kripto Korku & Açgözlülük Endeksi: {today['value']} ({today['value_classification']}) | "
            f"önceki gün: {prev['value']}"]


_FARSIDE_DATE = re.compile(r"^\d{1,2} [A-Z][a-z]{2} \d{4}$")


def _farside(asset: str) -> list[str]:
    """Farside Investors spot ETF net akış tablosu (milyon USD). En iyi çaba."""
    resp = SESSION.get(f"https://farside.co.uk/{asset}/", timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, flags=re.S | re.I)
    parsed = []
    for row in rows:
        cells = [clean_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S | re.I)]
        if len(cells) > 3 and _FARSIDE_DATE.match(cells[0]):
            total = cells[-1].replace(",", "")
            if total in ("", "-"):
                continue
            neg = total.startswith("(")
            try:
                val = float(total.strip("()"))
            except ValueError:
                continue
            parsed.append((cells[0], -val if neg else val))
    if not parsed:
        return []
    last = parsed[-5:]
    label = {"btc": "ABD spot Bitcoin ETF", "eth": "ABD spot Ethereum ETF", "sol": "ABD spot Solana ETF"}[asset]
    series = ", ".join(f"{d}: {v:+,.1f}" for d, v in last)
    return [f"{label} günlük net akış (milyon USD, Farside): {series}"]


_YAHOO = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^SOX": "PHLX Yarı İletken Endeksi (SOX)",
          "NVDA": "NVIDIA", "TSM": "TSMC (ADR)", "ASML": "ASML", "AMD": "AMD",
          "DX-Y.NYB": "Dolar Endeksi (DXY)", "^TNX": "ABD 10Y tahvil faizi (x10)", "GC=F": "Altın vadeli",
          "COIN": "Coinbase", "MSTR": "Strategy (MSTR)", "IBIT": "iShares Bitcoin Trust (IBIT)",
          "BZ=F": "Brent petrol vadeli (USD/varil)", "^VIX": "VIX korku endeksi",
          "^STOXX50E": "Euro Stoxx 50", "^N225": "Nikkei 225"}


def _yahoo() -> list[str]:
    lines = []
    for sym, name in _YAHOO.items():
        try:
            r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                            params={"range": "5d", "interval": "1d"}, timeout=config.HTTP_TIMEOUT)
            res = r.json()["chart"]["result"][0]
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) < 2:
                continue
            chg = (closes[-1] / closes[-2] - 1) * 100
            lines.append(f"{name}: son kapanış {closes[-1]:,.2f} | günlük değişim {chg:+.2f}%")
        except Exception as exc:
            log.debug("Yahoo %s alınamadı: %s", sym, exc)
    return lines


_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,11}$")


def fetch_quote(symbol: str) -> dict | None:
    """Kart etiketi için tek bir sembolün son fiyatı ve günlük değişimi (Yahoo Finance).
    Rakam modelden değil doğrudan veri kaynağından gelir; alınamazsa etiket gösterilmez."""
    symbol = (symbol or "").strip().upper()
    if not _TICKER_RE.match(symbol):
        return None
    try:
        r = SESSION.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                        params={"range": "5d", "interval": "1d"}, timeout=config.HTTP_TIMEOUT)
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        return {"symbol": symbol.removesuffix("-USD"), "last": closes[-1],
                "change": (closes[-1] / closes[-2] - 1) * 100}
    except Exception as exc:
        log.warning("Sembol verisi alınamadı (%s): %s", symbol, exc)
        return None


def fetch_market_snapshot() -> str:
    lines: list[str] = []
    for name, fn in (("CoinGecko", _coingecko), ("Korku&Açgözlülük", _fear_greed),
                     ("Farside BTC", lambda: _farside("btc")), ("Farside ETH", lambda: _farside("eth")),
                     ("Yahoo", _yahoo)):
        try:
            got = fn()
            lines.extend(got)
            log.info("Piyasa verisi %-16s %d satır", name, len(got))
        except Exception as exc:
            log.warning("Piyasa verisi alınamadı: %s (%s)", name, exc)
        time.sleep(0.3)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"PİYASA ANLIK GÖRÜNÜMÜ ({stamp}):\n" + "\n".join(f"- {l}" for l in lines)
