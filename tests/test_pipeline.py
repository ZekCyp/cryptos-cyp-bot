"""Ağ bağlantısı olmadan uçtan uca test: python -m unittest discover tests"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from bot import config, main, sources, validate

MARKET = ("PİYASA ANLIK GÖRÜNÜMÜ:\n- BTC fiyat: 108,245.12 USD | 24s değişim: +2.31%\n"
          "- ABD spot Bitcoin ETF günlük net akış (milyon USD, Farside): 21 Oct 2026: -312.6, 22 Oct 2026: +523.4")
ARTICLE = ("U.S. spot bitcoin ETFs drew $523.4 million in net inflows on Wednesday, ending a four-day streak "
           "of outflows that totaled $1.18 billion. BlackRock's IBIT led with $401 million.")

GOOD = {
    "category": "INSTITUTIONAL FLOWS & ETF",
    "headline": "Spot Bitcoin ETF'lerinde dört günlük çıkış serisi sona erdi",
    "metric1": {"label": "24 Saatlik Net Akış", "value": "+523,4 Milyon $"},
    "metric2": {"label": "Önceki 4 Günlük Çıkış", "value": "-1,18 Milyar $"},
    "summary": "IBIT'in 401 milyon $ ile öncülük ettiği girişler kurumsal talebin toparlandığını gösteriyor.",
    "image_prompt": "dark navy terminal, neon data streams, no text, no letters, no logos",
    "hook": "Dört seanslık çıkışın ardından ETF kanalında yön değişti.",
    "context": "BTC 108.245 $ seviyesinde, günlük bazda %2,31 yükselişte.",
    "impacts": {"institutional": "Girişler en likit fonlarda yoğunlaştı.",
                "price": "Spot talep satış baskısını dengeliyor.",
                "retail": "Tek günlük veri trend teyidi değildir."},
    "turkey_impact": "Kurumsal talebin toparlanması BTC/TL fiyatına da yansır; dolar/TL hareketi TL bazlı getiriyi "
                     "ayrıca etkiler.",
    "cta": "Sizce bu giriş kalıcı bir dönüşün başlangıcı mı?",
}


def _news():
    now = datetime.now(timezone.utc)
    return [sources.NewsItem(1, "CoinDesk", "Bitcoin ETFs snap four-day outflow streak", ARTICLE[:200],
                             "https://example.com/a", now),
            sources.NewsItem(2, "CNBC Technology", "Nvidia shares rise", "Nvidia rose.", "https://example.com/b", now),
            sources.NewsItem(3, "The Block", "Stablecoin bill advances", "Senate vote.", "https://example.com/c", now)]


class FakeLLM:
    def __init__(self, drafts):
        self.drafts = list(drafts)

    def generate_json(self, system, user, schema, temperature=0.5):
        if "selected_id" in schema["properties"]:
            return {"selected_id": 1, "runner_up_id": 2, "related_ids": [3], "reason": "ETF akışı"}
        return json.loads(json.dumps(self.drafts.pop(0)))


class ValidationTests(unittest.TestCase):
    def test_numbers_in_source_pass(self):
        post = main.normalize(json.loads(json.dumps(GOOD)), _news()[0])
        self.assertEqual(validate.check_post(post, ARTICLE + MARKET), [])

    def test_invented_number_blocked(self):
        bad = json.loads(json.dumps(GOOD))
        bad["metric2"]["value"] = "-2,7 Milyar $"           # kaynakta yok
        post = main.normalize(bad, _news()[0])
        errs = validate.check_post(post, ARTICLE + MARKET)
        self.assertTrue(any("2,7" in e for e in errs), errs)

    def test_clickbait_blocked(self):
        bad = json.loads(json.dumps(GOOD))
        bad["hook"] = "Dostlar Bitcoin uçuyoruz!"
        errs = validate.check_post(main.normalize(bad, _news()[0]), ARTICLE + MARKET)
        self.assertTrue(any("Yasaklı" in e for e in errs), errs)

    def test_investment_advice_blocked(self):
        bad = json.loads(json.dumps(GOOD))
        bad["turkey_impact"] = "Bu seviyeler alım fırsatı sunuyor."
        errs = validate.check_post(main.normalize(bad, _news()[0]), ARTICLE + MARKET)
        self.assertTrue(any("Yasaklı" in e for e in errs), errs)

    def test_caption_has_turkey_section(self):
        post = main.normalize(json.loads(json.dumps(GOOD)), _news()[0])
        self.assertIn("TÜRK YATIRIMCI İÇİN NE ANLAMA GELİYOR?", post["caption"])
        self.assertNotIn(config.ATTRIBUTION_LINE, post["caption"])     # atıf varsayılan olarak kapalı


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(config, k, self.tmp / v) for k, v in
                        (("OUTPUT_DIR", "output"), ("POSTS_DIR", "posts"), ("STATE_DIR", "state"),
                         ("HISTORY_FILE", "state/history.json"), ("ROOT", "."))]
        (self.tmp / ".").mkdir(exist_ok=True)
        for p in self.patches:
            p.start()
        mock.patch.object(sources, "fetch_news", lambda *a, **k: _news()).start()
        mock.patch.object(sources, "fetch_market_snapshot", lambda: MARKET).start()
        mock.patch.object(sources, "fetch_article_text", lambda url: ARTICLE).start()
        mock.patch.object(config, "MIN_ARTICLE_CHARS", 100).start()
        mock.patch.dict("os.environ", {"POST_MODE": "haber", "POST_FORMAT": "kaydirmali"}).start()

    def tearDown(self):
        mock.patch.stopall()

    def _run(self, drafts):
        with mock.patch("bot.writer.Gemini", lambda: FakeLLM(drafts)):
            return main.prepare()

    def test_prepare_success_after_retry(self):
        bad = json.loads(json.dumps(GOOD))
        bad["metric1"]["value"] = "+999 Milyon $"          # ilk taslak uydurma rakam içeriyor
        self.assertEqual(self._run([bad, GOOD]), 0)
        post = json.loads((self.tmp / "output/post.json").read_text())
        self.assertEqual(post["metric1"]["value"], "+523,4 Milyon $")
        self.assertTrue((self.tmp / post["image_path"]).exists())

    def test_prepare_refuses_when_unverifiable(self):
        bad = json.loads(json.dumps(GOOD))
        bad["metric1"]["value"] = "+999 Milyon $"
        self.assertEqual(self._run([bad] * 30), 1)          # yayın iptal edilmeli
        self.assertFalse((self.tmp / "output/post.json").exists())


class CloseReelTests(unittest.TestCase):
    def test_silent_close_reel_renders(self):
        from bot import rates, reels
        if not reels._ffmpeg():
            self.skipTest("ffmpeg yok")
        rows = [rates._row(c, n, v, ch, 2) for c, n, v, ch in
                (("USD/TRY", "Dolar/TL", 42.51, 0.12), ("XU100", "BIST 100", 10234.5, -0.8),
                 ("ALTIN", "Gram altın", 5712.3, 1.1), ("BTC", "Bitcoin", 91234.0, 2.4))]
        out = Path(tempfile.mkdtemp()) / "close.mp4"
        with mock.patch.object(rates, "CLOSE_HOLD", 0.5), mock.patch.object(rates, "CLOSE_OUTRO", 0.5):
            made = rates.build_close_reel(rows, datetime(2026, 11, 25).date(), datetime(2026, 11, 26, 9), out)
        self.assertIsNotNone(made)
        self.assertGreater(out.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
