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

## Giriş ve modüller

Sisteme kullanıcı adı ve parolayla girilir. Giriş sonrası **modül seçim ekranı** açılır;
kullanıcı yalnızca yetkili olduğu modülleri açabilir.

| Modül | Durum |
|---|---|
| **Ring Planlama** | Hazır |
| Rotalı Araç Planlama | Yakında |
| İhracat Planlama | Yakında |
| Araç Talep ve Tedarik | Yakında (sözleşmeli nakliyeciler de erişecek) |
| **Master Data** | Hazır — modüllerin ortak ürün verisi |
| **Sistem Yönetimi** | Hazır — kullanıcılar, yetkiler, veri yönetimi |

**Roller:** Yönetici, Planlamacı, Depo, Nakliyeci, İzleyici. Yetki modül bazında
*görüntüleme* ya da *düzenleme* olarak verilir; yöneticiler her modüle erişir.

**Parola kuralları:** en az 10 karakter, en az bir büyük harf, bir küçük harf, bir rakam
ve bir özel karakter. Parolalar scrypt ile saklanır. 5 hatalı denemede hesap kilitlenir,
kilidi yönetici açar. Yeni kullanıcı ve parola sıfırlamada geçici parola üretilir ve ilk
girişte değiştirilmesi zorunludur.

İlk çalıştırmada `admin` hesabı ve geçici parolası konsola yazılır. Kaçırılırsa ya da
unutulursa program kapalıyken `python -m scripts.yonetici` komutu yeni bir geçici parola
üretir (`--parola "..."` ile kendi parolanızı belirleyebilirsiniz, `--liste` kullanıcıları
gösterir).

## Sunucuya kurulum

Ekip kullanımı, veritabanı seçimi (PostgreSQL), HTTPS, Windows servisi / systemd,
Azure seçeneği ve nakliyeci erişimi için → [`docs/SUNUCU-KURULUMU.md`](docs/SUNUCU-KURULUMU.md)

## Ekranlar

| Ekran | İşlev |
|---|---|
| **Modül Seçimi** (`/`) | Yetkili olunan modüllerin listesi |
| **Gösterge Paneli** (`/ring`) | Özet metrikler, planlamayı çalıştırma, bekleyen sipariş özeti |
| **Siparişler** | Excel aktarımı; beklemede / planlandı / tamamlandı / hatalı sekmeleri |
| **Planlar** | Plan listesi, filtre, Excel'e aktarma, tüm depoları tek seferde planlama, mix seçeneği |
| **Plan Detayı** | Plan içeriği, Axata no girişi, yükleme formu, statü işlemleri, plan geçmişi |
| **Master Data** | Ürün tanımlama (tek tek veya Excel ile toplu), palet içi adet |
| **Raporlar** | Aylık özet, ürün bazlı doluluk, sevk/Axata takibi, bekleyenlerin gerekçesi |
| **Sipariş İzleme** | Sipariş veya teslimat numarasıyla uçtan uca geçmiş sorgulama |
| **Veri Yönetimi** | Seçerek veri silme: planlanmamış siparişler, planlar, tümü |
| **Kullanıcılar** | Kullanıcı açma, rol ve modül yetkisi verme, parola sıfırlama |

## Planlama kuralları (özet)

1. Teslimat numaraları **bölünmez**; bir teslimatın tüm satırları aynı plandadır.
2. **Kapasite anahtar değerdir ve işgal edilen palet üzerinden hesaplanır.**
   Bütün depolar tır bazında planlanır; toplam **1,00 = araç %100 dolu**, alt limit
   **0,90**. Kırık palet araçta tam bir palet gözü kapladığı için miktar önce palete
   yuvarlanır: palet içi 15, tır kapasitesi 360 olan bir üründen 305 adet ham oranla
   %85 görünür ama gerçekte %87,5 yer kaplar — motor 305 değil **300 adetlik
   (20 tam palet)** bileşimi seçer.
3. **Hedef tam palet.** Palet, plan bazında hesaplanır: aynı ürünün farklı
   teslimatlardaki miktarları önce toplanır, sonra palete yuvarlanır. Palet içi adedi
   16 olan bir üründen 13 + 3 adet, iki kırık palet değil **tek dolu palet**tir.
   Yerleştirme, kırık palet israfını en aza indirecek plana yönelir.
4. **İki fazlı gruplama:**
   - *Faz 1* — her ürün kodu kendi içinde paketlenir (SKU saf planlar).
   - *Faz 2* — aracı dolduramayan artıklar aynı **ürün grubu** içinde birleştirilir
     (farklı ölçülerdeki paneller gibi). Planlama ekranındaki kutuyla kapatılabilir.
   - Farklı ürün grupları otomatik birleşmez; onun için "Seçilerek mix plan" kullanılır.
5. **Header code'lu ürünler ve aksesuarlar** (AKSESUAR, BACA, DİRSEK) her zaman ana
   ürünle aynı plandadır; aksesuar tek başına plan açmaz.
6. Üst limiti tek başına aşan teslimat, **istisna planı** olarak tek başına planlanır.
7. Alt limiti dolduramayan teslimatlar `BEKLEMEDE` kalır. Planlama ekranındaki
   **"Kalanları da planla"** kutusu işaretlenirse alt limit aranmaz; bu planlar
   **ESNETİLDİ** rozetiyle işaretlenir.
8. **Termin tarihi planlamayı etkilemez.**

**Depolar:** 64, 64-V, 64-P, 74, 74-V, 3, 03, 34, 36, 44 — hepsi anahtar ölçüsüyle.
Yükleme formundaki `64-D DEPO` satırı ayrı bir depo değil, depo 64'ün form üzerindeki
adıdır.

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
  services/      Excel aktarım, plan yaşam döngüsü, raporlama, yükleme formu, kullanıcılar
  guvenlik.py    parola politikası ve saklama (scrypt)
  moduller.py    modül tanımları
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
