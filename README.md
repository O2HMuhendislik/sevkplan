# Sevkiyat Planlama Sistemi

Sipariş verisinden otomatik sevkiyat planı üreten, planları sefer numarasıyla
takip eden ve depo operasyona yükleme formu çıkaran uygulama.

**Faz 1 (bu sürüm):** Depo `64` için **Ring planlaması** — 18–20 palet aralığında,
tek ürünlü, teslimat bölmeyen planlar.
**Faz 2 (sonraki):** Diğer depolar için tır planlaması (anahtar değer %100 doluluk).

İş kurallarının tamamı → [`docs/ANALIZ.md`](docs/ANALIZ.md)
Excel formatları → [`docs/veri-formatlari.md`](docs/veri-formatlari.md)

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
```

## Çalıştırma

```bash
uvicorn app.main:uygulama --reload
```

Tarayıcıdan <http://127.0.0.1:8000> adresine gidin. Veritabanı ilk açılışta
`veri/sevkplan.db` olarak otomatik oluşur.

### Demo veriyle denemek

```bash
python -m scripts.ornek_veri
```

8 ürün ve 60 sipariş satırı üretip planlamayı çalıştırır; örnek Excel dosyaları
`veri/ornek/` altına yazılır.

## Ekranlar

| Ekran | İşlev |
|---|---|
| **Gösterge Paneli** | Özet metrikler, planlamayı çalıştırma, bekleyen sipariş özeti |
| **Siparişler** | Excel aktarımı; beklemede / planlandı / tamamlandı / hatalı sekmeleri |
| **Planlar** | Plan listesi, filtre, Excel'e aktarma, manuel mix plan |
| **Plan Detayı** | Plan içeriği, Axata no girişi, yükleme formu, statü işlemleri, plan geçmişi |
| **Master Data** | Ürün tanımlama (tek tek veya Excel ile toplu), palet içi adet |
| **Raporlar** | Aylık özet, ürün bazlı doluluk, bekleyenlerin gerekçesi |
| **Sipariş İzleme** | Sipariş veya teslimat numarasıyla uçtan uca geçmiş sorgulama |

## Planlama kuralları (özet)

1. Teslimat numaraları **bölünmez**; bir teslimatın tüm satırları aynı plandadır.
2. Bir planda **tek ürün (SKU)** bulunur. Farklı ürünler yalnızca manuel mix planla birleşir.
3. **Header code**'lu ürünler (ana ürün + aksesuar) her zaman aynı plandadır.
4. Kapasite **20 palet**, alt limit **18 palet**. Altında kalan teslimatlar beklemede kalır.
5. Tek başına 20 paleti aşan teslimat, **istisna planı** olarak tek başına planlanır.
6. Sıralama termin tarihine göredir; eski siparişler önce planlanır.
7. Palet = `yukarı yuvarla(miktar / palet içi adet)`; kırık palet bir tam palet sayılır.

## Sefer numarası

`2608D1001` = `26` yıl · `08` ay · `D` Ring belge kodu · `1001` sayaç.
Sayaç her ay `1001`'den başlar. İptal edilen planın numarası geri kullanılmaz.

## Proje yapısı

```
app/
  domain/        saf iş mantığı (planlama motoru, sefer no, kapasite profilleri)
  services/      Excel aktarım, plan yaşam döngüsü, raporlama, yükleme formu
  templates/     arayüz şablonları
  main.py        web uygulaması (FastAPI)
docs/            analiz ve veri formatı dokümanları
scripts/         demo veri üreteci
tests/           birim ve uçtan uca testler
```

Planlama motoru (`app/domain/`) veritabanı ve arayüzden tamamen bağımsızdır;
kurallar tek başına test edilebilir.

## Test

```bash
python -m pytest -q
```
