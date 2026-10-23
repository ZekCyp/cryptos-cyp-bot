# @Cryptos.cyp Otomatik Piyasa İstihbaratı Botu

Her gün **~09:00** ve **~18:00**'de (İstanbul saati) son 24 saatin en kritik piyasa/kripto/çip
haberini seçer, kurumsal tonda Türkçe içerik yazar, rakamları kaynağa karşı doğrular, 1080×1350
kartı üretir ve Instagram'da **kendiliğinden** yayınlar. Tamamen ücretsiz servislerle çalışır.

| Bileşen | Servis | Maliyet |
|---|---|---|
| Zamanlayıcı ve çalıştırma | GitHub Actions (herkese açık repo) | 0 ₺ |
| Haber | 12 RSS kaynağı (CoinDesk, The Block, CNBC, SEC...) | 0 ₺ |
| Piyasa verisi | CoinGecko, Farside ETF akışları, Yahoo Finance, Korku & Açgözlülük | 0 ₺ |
| Yazım | Google Gemini API ücretsiz katman | 0 ₺ |
| Arka plan görseli | Cloudflare Workers AI – Flux (günde 10.000 ücretsiz nöron) | 0 ₺ |
| Yayın | Instagram Graph API | 0 ₺ |

## Güvenlik kilitleri (onaysız yayın için)

- **Rakam doğrulaması:** Metindeki her anlamlı sayı, haber metninde veya piyasa verisinde
  karşılığı olan bir değer olmak zorunda. Değilse taslak yeniden yazdırılır; iki haberde de
  geçemezse o saatin paylaşımı **iptal edilir** (yanlış veri yayınlamaktansa boş geçer).
- **Üslup filtresi:** "uçuyoruz", "patladı", "dostlar", "şok" vb. ifadeler engellenir.
- **Tekrar engeli:** Son 14 günde işlenen haber tekrar seçilmez.
- **Yasal not:** Her açıklamaya "yatırım tavsiyesi değildir" ve kaynak satırı eklenir.
- Çalışma başarısız olursa GitHub size otomatik e-posta gönderir.

---

## Kurulum (yaklaşık 30-40 dakika, bir kez)

### 1. GitHub deposu
1. github.com'da ücretsiz hesap açın → **New repository** → ad: `cryptos-cyp-bot` →
   **Public** seçin (ücretsiz sınırsız çalışma süresi ve görselin Instagram'a herkese açık
   adresten verilebilmesi için gerekli; API anahtarlarınız gizli kalır).
2. Bu klasördeki tüm dosyaları depoya yükleyin (**Add file → Upload files**, klasörü sürükleyin).
   > `.github` klasörü bazı bilgisayarlarda gizli görünür. Yüklenmediyse **Add file → Create new
   > file** ile ad kısmına `.github/workflows/post.yml` yazıp dosyanın içeriğini yapıştırın.
3. **Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.

### 2. Gemini API anahtarı
1. aistudio.google.com → **Get API key → Create API key**.
2. Faturalandırma (billing) **eklemeyin**; böylece ücret çıkması mümkün olmaz.

### 3. Cloudflare (görsel üretimi)
1. dash.cloudflare.com'da ücretsiz hesap açın (kart gerekmez).
2. **Account ID**: sol menü → *AI → Workers AI* sayfasında veya hesap ana sayfasının sağında.
3. **API Token**: sağ üst profil → *My Profile → API Tokens → Create Token* → **Workers AI**
   şablonu → oluştur ve kopyalayın.
   > Bu adımı atlarsanız sistem yine çalışır; kart, kodla üretilen yedek arka planı kullanır.

### 4. Instagram erişimi (Facebook sayfası gerekmez)
1. developers.facebook.com → **My Apps → Create App** → kullanım alanı olarak Instagram
   içerik yönetimini seçin.
2. Uygulamada **Instagram → API setup with Instagram login** bölümüne girin.
3. **Generate access tokens → Add account** → @cryptos.cyp ile giriş yapıp izin verin
   (`instagram_business_basic`, `instagram_business_content_publish`).
   > Instagram'da *Ayarlar → Uygulamalar ve web siteleri → Test daveti* çıkarsa kabul edin.
4. Ekranda görünen **Instagram User ID** ve **Access Token** değerlerini kopyalayın.
   Token 60 gün geçerlidir; bot her çalışmada süresini otomatik uzatır.
> Meta panelindeki menü adları zaman zaman değişir; yukarıdaki adımların özü aynıdır.

### 5. (Önerilen) Token'ın kendini yenileyebilmesi için GitHub anahtarı
GitHub → sağ üst profil → *Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate* → yalnızca `cryptos-cyp-bot` deposu → *Repository permissions →
Secrets: Read and write* → oluşturun. (En fazla 1 yıl geçerli; süresi dolunca yenileyin.)

### 6. Anahtarları depoya ekleyin
Depo → **Settings → Secrets and variables → Actions → New repository secret**:

| Ad | Değer |
|---|---|
| `GEMINI_API_KEY` | 2. adımdaki anahtar |
| `CF_ACCOUNT_ID` | 3. adımdaki Account ID |
| `CF_API_TOKEN` | 3. adımdaki token |
| `IG_USER_ID` | 4. adımdaki Instagram User ID |
| `IG_ACCESS_TOKEN` | 4. adımdaki Access Token |
| `GH_PAT` | 5. adımdaki token (isteğe bağlı) |

### 7. Deneme ve canlıya alma
1. Depo → **Actions** → *Cryptos.cyp otomatik paylaşım* → **Run workflow**
   (*Deneme modu* işaretli) → çalışma bitince en alttaki **Artifacts** bölümünden kartı ve
   metni indirip inceleyin.
2. Memnunsanız aynı butonla **deneme modu işaretsiz** çalıştırın → ilk gerçek paylaşım.
3. Bundan sonra sistem her gün iki kez kendiliğinden çalışır. Başka bir şey yapmanız gerekmez.

---

## Ayarlar

| Ne değişecek | Nerede |
|---|---|
| Paylaşım saatleri | `.github/workflows/post.yml` → `cron` satırları (UTC; TSİ − 3 saat) |
| Haber kaynakları | `bot/config.py` → `FEEDS` |
| Etiketler, imza, yasal not | `bot/config.py` |
| Editör talimatı ve ton | `bot/writer.py` → `EDITOR_SYSTEM`, `WRITE_TASK` |
| Kart renkleri ve yerleşim | `bot/card.py` |
| Belirli bir Gemini modeli | Settings → Variables → `GEMINI_MODEL` (boşsa otomatik seçilir) |

## Sorun giderme

| Belirti | Neden / Çözüm |
|---|---|
| "Hiçbir Gemini modeli yanıt vermedi" | Ücretsiz günlük kota dolmuş olabilir; ertesi gün kendiliğinden düzelir. |
| "Doğrulamadan geçen içerik üretilemedi" | Güvenlik kilidi devrede; o saat paylaşım atlandı, normal durumdur. |
| Instagram `code=190` | Token geçersiz/süresi dolmuş → 4. adımı tekrarlayıp `IG_ACCESS_TOKEN`'ı güncelleyin. |
| Instagram `2207042` | Günlük API paylaşım sınırı aşıldı. |
| Zamanlanmış çalışma durdu | GitHub, 60 gün hareketsiz depolarda zamanlayıcıyı kapatır; bot her paylaşımda depoya yazdığı için normalde olmaz. Actions sekmesinden yeniden etkinleştirin. |

Yerel test (isteğe bağlı): `pip install -r requirements.txt && python -m unittest discover tests`
ve ağsız örnek kart için `python -m bot.main demo`.
