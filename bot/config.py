"""Merkezi ayarlar. Gizli anahtarlar burada değil, ortam değişkenlerinde (GitHub Secrets) durur."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
POSTS_DIR = ROOT / "posts"
OUTPUT_DIR = ROOT / "output"
FONTS_DIR = ROOT / "fonts"
HISTORY_FILE = STATE_DIR / "history.json"

SIGNATURE = "KRİPTO İSTİHBARATI | @CRYPTOS.CYP"
HASHTAGS = "#CryptosCYP #Bitcoin #KriptoPara #Web3 #Borsa #Finans #BTC #Yatırım"
DISCLAIMER = "Bu içerik bilgilendirme amaçlıdır, yatırım tavsiyesi değildir."

# Haber kaynakları (RSS). Biri çalışmazsa diğerleriyle devam edilir.
FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
    "The Defiant": "https://thedefiant.io/api/feed",
    "CNBC Markets": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "CNBC Technology": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Investing.com": "https://www.investing.com/rss/news_25.rss",
    "SEC Press": "https://www.sec.gov/news/pressreleases.rss",
    "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
}

NEWS_WINDOW_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "24"))
MAX_ITEMS_TO_MODEL = 45          # modele gönderilecek en fazla haber
MIN_ARTICLE_CHARS = 900          # bundan kısa metin = ücretli/okunamayan haber, atlanır
HISTORY_DAYS = 14                # aynı haberi tekrar paylaşmama süresi

# Instagram Graph API (Instagram Login)
IG_API_HOST = "https://graph.instagram.com"
IG_API_VERSION = os.getenv("IG_API_VERSION", "v26.0")

# Görsel
CARD_W, CARD_H = 1080, 1350      # Instagram 4:5 dikey
JPEG_QUALITY = 92

HTTP_TIMEOUT = 25
USER_AGENT = "CryptosCYP-IntelBot/1.0 (+https://instagram.com/cryptos.cyp)"
