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
# Instagram gönderi başına en fazla 5 etiket kabul ediyor: 1 marka etiketi + en fazla 4 konu etiketi.
BRAND_TAG = "#CryptosCYP"
MAX_HASHTAGS = 5
# Model uygun etiket öneremezse kategoriye göre kullanılacak konu etiketleri
DEFAULT_TOPIC_TAGS = {
    "CRYPTO": ["#Bitcoin", "#Kripto", "#KriptoPara", "#BTC"],
    "ETF": ["#Bitcoin", "#ETF", "#Kripto", "#Borsa"],
    "SEMICONDUCTOR": ["#YapayZeka", "#Çip", "#Teknoloji", "#Borsa"],
    "MACRO": ["#Ekonomi", "#Faiz", "#Fed", "#Piyasalar"],
    "REGULATION": ["#Kripto", "#Regülasyon", "#SEC", "#Piyasalar"],
    "GEOPOLITICS": ["#Ekonomi", "#Petrol", "#Altın", "#Piyasalar"],
    "": ["#Ekonomi", "#Borsa", "#Kripto", "#Piyasalar"],
}
HASHTAGS = BRAND_TAG + " #Bitcoin #Kripto #Borsa #Ekonomi"   # geriye dönük uyumluluk (5 etiket)
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
    # Jeopolitik / genel gelişmeler (yalnızca piyasa etkisi ölçülebiliyorsa seçilir)
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "CNBC World": "https://www.cnbc.com/id/100727362/device/rss/rss.html",
}

# Genel haber akışları çok hacimli; finans/kripto haberlerini bastırmasın diye sınırlı sayıda alınır
FEED_LIMITS = {"BBC Business": 12, "BBC World": 12, "CNBC World": 12}

NEWS_WINDOW_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "24"))
MAX_ITEMS_TO_MODEL = 60          # modele gönderilecek en fazla haber
MIN_ARTICLE_CHARS = 900          # bundan kısa metin = ücretli/okunamayan haber, atlanır
HISTORY_DAYS = 14                # aynı haberi tekrar paylaşmama süresi

# Instagram Graph API (Instagram Login)
IG_API_HOST = "https://graph.instagram.com"
IG_API_VERSION = os.getenv("IG_API_VERSION", "v26.0")

# Görsel
# Reels: "gün-saat" çiftleri (gün: 0=pazartesi ... 6=pazar). Varsayılan: tüm haber paylaşımları Reels
# (her gün 13, 18, 21; pazar ve pazartesi 09:00 haberi de). Sabah kapanış özeti görsel olarak kalır.
_ALL_NEWS_SLOTS = ",".join([f"{d}-{h}" for d in range(7) for h in (13, 18, 21)] + ["6-9", "0-9"])
REELS_SLOTS = os.getenv("REELS_SLOTS") or _ALL_NEWS_SLOTS

# ElevenLabs seslendirme (anahtar yoksa video sessiz üretilir)
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL") or "eleven_flash_v2_5"   # en ekonomik model
# Seslendirilecek Reels saatleri ("gün-saat"; "*" = her gün). Diğer Reels sessiz + altyazılı çıkar.
# Varsayılan: her gün yalnızca 18:00 (ayda ~30 Reels × ~400 karakter ≈ 12.000 kredi)
VOICED_SLOTS = os.getenv("VOICED_SLOTS") or "*-18"
REEL_OUTRO = "Doğru borsa haberleri için bizi takip edin."   # bir kez seslendirilir, sonra önbellekten
NEWS_STORY_ENABLED = os.getenv("NEWS_STORY_ENABLED", "true").lower() not in ("0", "false", "no")
CAROUSEL_ENABLED = os.getenv("CAROUSEL_ENABLED", "true").lower() not in ("0", "false", "no")
CARD_W, CARD_H = 1080, 1350      # Instagram 4:5 dikey
JPEG_QUALITY = 92

HTTP_TIMEOUT = 25
USER_AGENT = "CryptosCYP-IntelBot/1.0 (+https://instagram.com/cryptos.cyp)"
