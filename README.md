# Sevkiyat Planlama Sistemi

Sipariş verisinden otomatik sevkiyat planı üreten, planları sefer numarasıyla
takip eden ve depo operasyona yükleme formu çıkaran uygulama.

**Faz 1 (bu sürüm):** **Ring planlaması** — depo 64 palet ölçüsüyle (18–20 palet),
depo 74 anahtar değerle (%90–100). Teslimat bölünmez, planda tek ürün grubu bulunur.
**Faz 2 (sonraki):** Tır planlaması — aynı anahtar değer altyapısı, farklı belge kodu.

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

8 ürün ve 80 sipariş satırı üretip her iki depo için planlamayı çalıştırır; örnek
Excel dosyaları `veri/ornek/` altına yazılır.

### Kaynak master datadan temiz dosya üretmek

```bash
python -m scripts.masterdata_hazirla "Ring Planları.xlsx" veri/ornek/urun_masterdata.xlsx
```

Kaynak kitaptaki `masterdata` sayfasını bulur, `#N/A` değerlerini temizler, ürün
gruplarını normalize eder ve eksik kapasite verisi olan ürünleri ayrı bir sayfada
gerekçesiyle listeler.

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
2. Bir planda **tek ürün grubu** bulunur (PANEL, KOMBİ, TERMOSİFON …). Farklı gruplar
   yalnızca manuel mix planla birleşir. SKU seviyesine geçmek için
   `app/config.py` → `PLANLAMA_SEVIYESI = "SKU"`.
3. **Header code**'lu ürünler ve **aksesuarlar** (AKSESUAR, BACA, DİRSEK) her zaman
   ana ürünle aynı plandadır.
4. Kapasite depoya göre iki ölçüden biriyle hesaplanır:

   | Depo | Ölçü | Üst / alt limit | Kullanılan master data alanı |
   |---|---|---|---|
   | 64, 64-D, 64-V, 64-P | Palet | 20 / 18 | Palet içi adet |
   | 74, 74-V | Anahtar değer | 1.00 / 0.90 | Tır yükleme adeti |

   `palet = yukarı yuvarla(miktar / palet içi adet)` — kırık palet bir tam palet sayılır.
   `anahtar = miktar / tır yükleme adeti` — toplam 1.0 olunca araç %100 dolu.
5. Üst limiti tek başına aşan teslimat, **istisna planı** olarak tek başına planlanır.
6. Sıralama termin tarihine göredir; eski siparişler önce planlanır.
7. Alt limitin altında kalan teslimatlar planlanmaz, `BEKLEMEDE` statüsünde kalır.

## Sefer numarası

`2608D1001` = `26` yıl · `08` ay · `D` Ring belge kodu · `1001` sayaç.
Sayaç her ay `1001`'den başlar. İptal edilen planın numarası geri kullanılmaz.

## Yükleme formu

Depo operasyonun kullandığı **YÜKLEME FORMLARI (D-RİNG)** düzeni birebir üretilir:
form no, sefer no, plan sevk tarihi, depo/AXATA kutusu, satır tablosu, toplam adet ve
imza alanları. Axata iş emri numarası planın deposuna karşılık gelen satıra yazılır ve
**numara girilmeden plan gönderildi olarak işaretlenemez**. Bir günün bütün planları
tek dosyaya, her biri ayrı sayfaya basılacak şekilde alt alta yazılabilir.

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
