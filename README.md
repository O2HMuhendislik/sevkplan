# Vaillant Group Nakliye Yönetim Sistemi

Sipariş verisinden otomatik sevkiyat planı üreten, planları sefer numarasıyla
takip eden ve depo operasyona yükleme formu çıkaran uygulama.

Üç planlama modülü hazır: **Ring** (depo çıkışlı, ürün bazlı), **İç Piyasa**
(müşteri ve bölge bazlı; FTL, rutin/parsiyel, kargo) ve **İhracat** (müşteri bazlı,
tek noktaya giden tır/konteyner). Her modülün **sipariş havuzu ayrıdır**; hepsi bir
arada yalnızca **Raporlama** modülünde görünür.

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

### Programla gelen master data

Şirketin kendi verisi programa gömülüdür ve **ilgili tablo boşsa ilk açılışta
otomatik yüklenir** — hiçbir dosya yüklemeden çalışmaya başlanabilir:

| Dosya | İçerik |
|---|---|
| `veri/ornek/ihracat_urun_masterdata.xlsx` | 2.859 ihracat ürünü: palet içi adet, tır ve konteyner yükleme adetleri (yeni ve eski hesap), desi, ağırlık, ölçüler |
| `veri/ornek/ihracat_masterdata.xlsx` | 198 ihracat müşterisi: ülke, araç tipi, sefer kodu (N/E), yükleme tipi, azami tonaj, notlar |
| `veri/ornek/ic_piyasa_masterdata.xlsx` | 5.108 iç piyasa müşterisi: il, ilçe, bölge, tır girişi |

Tablo doluysa hiçbir şey yapılmaz; ekrandan yüklenen güncel master data asla gömülü
dosyayla ezilmez. Dosyalar şirketin `Hesaplama.xlsx` kitabından üretilir:

```bash
python -m scripts.ihracat_hesaplama_aktar Hesaplama.xlsx
```

`Ürün` sayfasını ürün master datasına çevirir, `Müşteriler` sayfasındaki yükleme
tipi/tonaj/notları geçmiş sevk verisinden gelen müşteri kayıtlarıyla birleştirir.
Aynı dosya ekrandan da yüklenebilir: **İhracat → Ürünler → Excel'den yükle**, sütun
başlıkları olduğu gibi tanınır.

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

## Kurumsal kimlik

Resmî Vaillant Group logosu markadır; depoda yalnızca bir **yer tutucu** durur
(`app/static/logo.svg`). Gerçek logo **ekrandan yüklenir**:

> **Sistem Yönetimi → Veri Yönetimi → Kurumsal logo → Logoyu yükle**

Yüklenen dosya `veri/marka/` altına yazılır — program klasörüne değil. Yeni sürüm
kurulduğunda (klasörün üzerine yeni zip açıldığında) logo **silinmez**, kod
değiştirmek de gerekmez. SVG en iyisidir (her ekranda net görünür); PNG, JPG ve WEBP
de kabul edilir, en fazla 2 MB. Logo başlıkta ve giriş ekranında beyaz zemin üzerinde
34 piksel yüksekliğinde gösterilir; yatay bir dosya en iyi sonucu verir. "Logoyu
kaldır" yer tutucuya döndürür.

### Renk paleti

Kaynak: **Vaillant Group Corporate Design Manual 2020, sayfa 16** (1.3.2 Colours –
Definition). Yedi kurumsal rengin tamamı `app/static/style.css` dosyasının başındaki
`:root` bloğunda `--vg-*` değişkenleri olarak duruyor; arayüz bunlardan ikisini
kullanıyor.

| # | Renk | RGB | HEX | Arayüzdeki yeri |
|---|---|---|---|---|
| 01 | Vaillant Group Green (Pantone 327 CU) | 0 / 136 / 125 | `#00887D` | Düğmeler, metrik değerleri, doluluk çubuğu, aktif sekme |
| 02 | Grey | 155 / 155 / 155 | `#9B9B9B` | Kenarlık (%40), tablo başlığı (%20) |
| 03 | Light Blue | 0 / 135 / 192 | `#0087C0` | (şu an kullanılmıyor) |
| 04 | Purple | 133 / 34 / 94 | `#85225E` | Uyarı ve hata — kartelada kırmızı yok |
| 05 | Beige | 133 / 121 / 107 | `#85796B` | "Axata bekliyor" rozeti |
| 06 | Yellow | 227 / 184 / 83 | `#E3B853` | "Taslak / beklemede" rozeti |
| 07 | Dark Blue | 42 / 80 / 124 | `#2A507C` | Başlık çubuğu, sayfa başlıkları, bağlantılar |

Karteladaki açık tonlar (%80, %70, %60, %40, %20, %10) da tanımlı. **Ara ton
uydurulmadı:** düğmenin üzerine gelme rengi yeşilin koyusu değil, kartelada tanımlı
%80 tonudur (`#4F9C95`).

Metin ve ikincil metin renkleri markanın parçası değildir — kurumsal kartelalar gövde
metni rengi tanımlamaz; okunabilirlik için nötr griler seçildi.

**Yazı tipi:** paylaşılan doküman yalnızca renk bölümünü kapsıyor ve kendisi Arial
kullanıyor; arayüz de Arial'dan başlayan bir yığın kullanıyor. Marka kılavuzunun
tipografi bölümü farklı bir yazı tipi tanımlıyorsa `style.css` içindeki tek bir
`font:` satırını değiştirmek yeterli.

## Giriş ve modüller

Sisteme kullanıcı adı ve parolayla girilir. Giriş sonrası **modül seçim ekranı** açılır;
kullanıcı yalnızca yetkili olduğu modülleri açabilir.

| Modül | Durum |
|---|---|
| **Ring Planlama** | Hazır |
| **İç Piyasa Sevkiyat Planlama** | Hazır — kamyon / tır, FTL / rutin / kargo |
| **İhracat Planlama** | Hazır — tır / konteyner, kara / deniz |
| **Raporlama** | Hazır — modüller arası liste ve plana alınma KPI'ı |
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
| **Raporlar** | Aylık özet, ürün bazlı doluluk, sevk/Axata takibi, bekleyenlerin gerekçesi, **master datası eksik olduğu için hiç planlanamayanlar** |
| **Sipariş İzleme** | Sipariş veya teslimat numarasıyla uçtan uca geçmiş sorgulama |
| **Veri Yönetimi** | Kurumsal logo yükleme; seçerek veri silme: planlanmamış siparişler, planlar, tümü |
| **Kullanıcılar** | Kullanıcı açma, rol ve modül yetkisi verme, parola sıfırlama |

### İç piyasa modülü (`/rota`)

| Ekran | İşlev |
|---|---|
| **Gösterge Paneli** (`/rota`) | Sevkiyat tipi, **araç (kamyon/tır)** ve bölge dağılımı, planlamayı çalıştırma |
| **Siparişler** | Sipariş dosyası yükleme; her müşterinin hangi tiple gideceği ve **gerekçesi**; alınamayan satırlar sebebiyle. Ring ile aynı sipariş havuzu |
| **Planlar** | Tip (FTL/rutin/kargo), **araç (kamyon/tır)**, bölge ve durum filtresi; günlük yükleme formu. Liste "FTL" yerine aracın adını yazar |
| **Plan Detayı** | **Araç (kamyon/tır)**, rota ve duraklar, son uğrak oranı, ortak yükleme notu, araç/şoför bilgisi, Axata, marka payı |
| **Müşteriler** | Müşteri master datası: il, ilçe, bölge, **tır girişi** (E/H/?), Excel ile toplu yükleme |
| **Raporlar** | Tip ve bölge bazında plan/durak/doluluk özeti, Excel'e aktarma |

### İhracat modülü (`/ihracat`)

| Ekran | İşlev |
|---|---|
| **Gösterge Paneli** (`/ihracat`) | Ülke ve taşıma modu dağılımı, planlamayı çalıştırma |
| **Siparişler** | Sipariş yükleme; müşteri bazında araç tipi, taşıma modu, hesap sürümü, palet sayısı, kaç araç gerekeceği ve hangi sınırın (hacim/ağırlık) dolduracağı |
| **Planlar** | Durum filtresi, günlük yükleme formu, Excel'e aktarma |
| **Plan Detayı** | Doluluk, palet/desi/ağırlık, yükleme tipi ve müşteri notu, çekici/dorse/mühür, Axata, marka payı |
| **Müşteriler** | Araç tipi, sefer kodu (N/E), yükleme tipi, azami tonaj, hesap sürümü ve müşteriye özel yükleme notu |
| **Ürünler** (`/ihracat/urunler`) | İhracat ürün master datası: palet içi adet, tır ve konteyner yükleme adetleri (yeni ve eski hesap), desi, ağırlık; ölçüsü eksik ürünlerin listesi |

### Raporlama modülü (`/raporlama`)

| Ekran | İşlev |
|---|---|
| **Özet ve KPI** | Modül bazında sipariş/plan sayıları; siparişin plana alınma süresi dağılımı ve termin gecikme oranı |
| **Tüm Siparişler** | Bütün modüllerin sipariş satırları, modül sekmeleriyle filtrelenir; her satırın plana alınma süresi |
| **Tüm Planlar** | Bütün modüllerin planları, modüle göre filtrelenir |

### Plan raporu (`/rapor/plan-raporu`)

Üç modülün de plan ekranındaki **“Plan raporu”** düğmesi aynı kitabı üretir; ekrandaki
durum/arama filtresi rapora da uygulanır. `modul` verilmezse kullanıcının yetkili
olduğu bütün modüller tek kitapta gelir.

| Sayfa | İçerik |
|---|---|
| **Özet** | Modül × durum kırılımı: plan, teslimat, adet, palet, ağırlık, ortalama doluluk; son satır genel toplam. İptal planlar özete girmez. |
| **Ürün Grubu** | Planlanan ürünlerin grup bazında toplam adedi — “bu dönem hangi gruptan kaç adet plana girdi”. Grubu tanımsız ürünler `GRUPSUZ` altında toplanır, böylece toplam plan adediyle eşleşir. |
| **Planlar** | Her planın künyesi: sefer, tarih, durum, araç/tip, depo, müşteri, il/ülke, durak, doluluk, kısıtlayan ölçü, marka payı. |
| **Sevk Durumu** | Operasyon takibi: Axata, nakliyeci, plaka, konteyner/mühür, şoför, mail tarihi, planın açılmasından bu yana geçen gün. |

Aynı kırılım ekranda da var: plan detayında **“Ürün grubu özeti”** kartı o araca hangi
gruptan kaç adet girdiğini gösterir.

## İç piyasa planlama kuralları (özet)

Ayrıntı ve verinin doğrulaması: [`docs/IC-PIYASA-ANALIZ.md`](docs/IC-PIYASA-ANALIZ.md)

1. **Sevkiyat tipi müşteri bazında** belirlenir; sırayla: Incoterms **EXW** → kargo,
   müşteri toplamı **10 desinin altında** → kargo, toplamı **3 paleti aşmıyorsa** →
   rutin/parsiyel, kalanı → **FTL**. Sefer numarası belge kodunu buradan alır:
   `2609S1001` (FTL), `2609R1001` (rutin), `2609K1001` (kargo).
2. **Araç kamyon mu tır mı?** Aynı yükün iki anahtar değeri vardır: kamyon ve tır.
   Kamyon küçüktür — tır yükleme adeti 468 olan bir üründen kamyona 252 adet girer,
   yani aynı yük tırın yarısını doldururken kamyonun tamamına yakınını doldurur.
   Bu yüzden **araç tipi yükleme bittikten sonra seçilir:** paketleme tır ölçüsüyle
   yapılır, yük bir kamyona sığıyorsa (kamyon anahtar değeri ≤ 1,00) plan kamyona
   iner ve doluluk kamyon kapasitesine göre ölçülür. Yarım kalan bir tır, dolu bir
   kamyondur; eskiden bu yükler "tır alt limitini dolduramadı" diye beklemede
   kalıyordu.
   *Doğrulama:* 2025'in gerçek 3.548 iç piyasa aracında **tır olarak çıkanların
   %0'ının** kamyon anahtar değeri 1,00'ın altında (yani kural hiçbir tırı yanlışlıkla
   kamyona indirmiyor), **kamyon olarak çıkanların** kamyon değeri medyan 0,95 / tır
   değeri medyan 0,49 — tam olarak "yarım tır = dolu kamyon" durumu.
3. **Tır giremeyen müşterinin aracı baştan kamyondur.** Müşteri master datasındaki
   *tır girişi* alanı `H` ise o müşteri ayrı planlanır: ölçüler kamyona göre
   hesaplanır, yükü 1,7 kamyonluksa iki kamyona bölünür. Aynı araca tır girebilen bir
   müşteri konmaz — yoksa araç tıra çıkar ve mal kapıya inemez. Master datada
   5.108 müşterinin 602'sine tır girmiyor, 3.422'sinde bu alan **boş**; boş olanlar
   tır varsayılır, doldurdukça planlama gerçeğe yaklaşır.
4. **Bölge bazlı rotalama.** Bir araca yalnızca aynı bölgedeki müşteriler yüklenir;
   bölgeler geçmiş FTL planlarından çıkarıldı (`app/domain/bolgeler.py`) ve müşteri
   ekranından değiştirilebilir.
5. **Durak sırası** yükleme tesisine uzaklığa göredir; en uzak il **son uğraktır** ve
   aracın en az **%15**'ini kaplamalıdır, aksi hâlde o durak araçtan çıkarılır.
6. FTL araçta en fazla **5 durak**; rutinde durak sınırı yoktur (sahada 25-30 durak).
7. **Rutin araç %50-60 dolulukta bırakılır.** Ölçüsü palete yuvarlanmaz: parsiyel
   araçta paletler karışık istiflenir, kırık palet tam palet gözü saymaz. FTL'de
   yuvarlanır — orada her müşterinin malı tam paletle yüklenir.
8. **Günlük sınır:** 35 FTL, 4 rutin. Aşan hacim gerekçesiyle beklemede kalır ve
   sonraki gün planlanır. Sınır, o gün daha önce üretilmiş planları da sayar.
9. **Bölünmez olan teslimattır, müşteri değil.** Bir aracı aşan müşterinin teslimatları
   birden çok araca dağıtılır; tek başına aracı aşan teslimat istisna planına gider.
10. **Ortak yükleme:** 64, 74 ve -1 depoları aynı araca yüklenebilir. Araç, hacmin
   çoğunu taşıyan depodan yüklenir; diğer depodaki malın satırına yükleme formunda
   *"… depoya gönderilmelidir"* notu düşülür. Aktarma için ayrı plan üretilmez.
11. **Tır girişi bilinmeyen müşteri** (alan boş) tır varsayılır; plan detayında ve
    sipariş önizlemesinde uyarı çıkar.

## İhracat planlama kuralları (özet)

1. **Araç tek noktaya gider:** plan = bir müşteri + bir araç. 2025 verisinde planların
   %98,3'ü tek müşterili; rota, durak ve son uğrak kuralı yoktur.
2. **Doluluk şirketin `Hesaplama.xlsx` dosyasındaki formülle ölçülür:**
   `DOLULUK = Σ(miktar / yükleme adeti)` — 1,00 araç %100 dolu demektir. Yükleme adeti
   ürün master datasından gelir ve araç tipine göre ayrıdır (tır / konteyner).
   Yanında `PALET = Σ(miktar / palet içi adet)`, `DESİ = Σ(birim desi × miktar)`,
   `AĞIRLIK = Σ(birim ağırlık × miktar)` hesaplanır ve forma basılır.
   *Doğrulama:* 2025'in 730 gerçek aracında bu formülün medyanı hem tırda hem
   konteynerde **tam %100**.
3. **İki hesap sürümü müşteriye göre seçilir.** Müşterinin notunda “ESKİ HESAPLAMA”
   geçiyorsa ürün master datasındaki `TIR-2 / KONTEYNER-2 / PALET İÇİ ADET-2`
   sütunları, geçmiyorsa temel sütunlar kullanılır. “PALET YÜKSELTME” geçen
   müşteride doluluk **1,2'ye bölünür** — paletler üst üste istiflenince araca %20
   daha fazla yük girer. Kural, yükleme tipi ve notlar metinlerinden otomatik çözülür
   (`app/domain/ihracat_hesap.py`), müşteri ekranında **Hesap** sütununda görünür.
4. **Ağırlık ikinci sınırdır:** hacim ya da ağırlık, hangisi önce dolarsa araç dolmuş
   sayılır; plan hangi sınırın doldurduğunu kaydeder. Varsayılan **tır 22.000 kg**,
   **konteyner 19.500 kg**; müşterinin azami tonajı bunun önüne geçer.
5. **Taşıma modu müşteriden çıkar:** konteyner yüklenen müşteri **deniz**, tır yüklenen
   **kara** yoludur. Şili konteyner, Romanya tır.
6. **Sefer belge kodu müşteri bazındadır:** `N` (NSC) ya da `E` (Export) —
   `2608E4001`. Geçmiş 9.708 satırda ikisi birebir bu alana göre ayrışıyor.
7. **Ölçüsü olmayan SKU planlamayı durdurmaz.** Master datada 2.859 üründen 166'sında
   tır/konteyner adedi ve desi boş; bu kalemler sipariş dosyasındaki desiden yaklaşık
   hesaplanır ve plan notunda hangi kodların yaklaşıldığı yazar.
8. **Alt limit araç başına değil müşteri toplamına** uygulanır: sorulan soru "bu
   müşteriye bugün araç kaldırmaya değer mi?" Cevap evetse araç sayısını teslimatların
   bölünmezliği belirler.
9. **Müşteriye özel yükleme notu** (hava yastığı, silika jel, paletsiz dökme) ve
   **yükleme tipi** (standart / palet yükseltme / dökme / köşebent) forma basılır.
   Not, formun sağ alt köşesinde kendi kutusundadır. Plan üretildikten **sonra**
   yazılan not da forma gelir: plandaki kopya boşsa müşteri master datasından okunur.
10. **Formun desi toplamı kendi satırlarının toplamıdır.** Satırda desi varsa o
    kullanılır; master datadaki birim desi yalnızca satırda değer yoksa devreye
    girer. (2026'nın 8.463 satırında ikisi %54 oranında birebir aynı.)

## Yükleme formları

Üç modülün formu da aynı görsel kurallara uyar:

* **Arka plandaki hücre kılavuz çizgileri kapalıdır** (`showGridLines`), ekranda ve
  çıktıda yalnızca formun kendi çizgileri görünür.
* **Her plan bloğu kalın bir çerçeve içindedir;** blok içindeki hücre çizgileri ince
  kalır. Bir kitapta birden çok plan varsa her biri kendi çerçevesiyle ayrı sayfaya
  basılır.
* **Uzun metinler kendi kutusuna sarılır.** Kırmızı hasar/HİT uyarısı ile ihracat
  formundaki müşteri notu birleştirilmiş, `wrap_text` verilmiş kutulardır; satır
  yüksekliği metne göre ayarlanır, böylece yazı komşu hücrelerin altında kalmaz.

## Ring planlama kuralları (özet)

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
   **ESNETİLDİ** rozetiyle işaretlenir ve beklemede satır kalmaz.
   Buna rağmen yerinde duran satırlar `BEKLEMEDE` değil **`HATALI`** olanlardır:
   master datası eksik oldukları için planlamaya hiç girmezler ve esnetme onları
   kurtarmaz. Raporlar ekranındaki *"Planlanamayan siparişler"* tablosu bunları
   gerekçesiyle listeler. Bir teslimattaki tek bir ürünün eksiği bütün teslimatı
   dışarıda bırakır.
8. **Ring yalnızca Eskişehir içi dağıtımdır.** Sipariş dosyasında `SehirAdi` alanı
   Eskişehir dışında bir il gösteren satırlar bu havuza **alınmaz**; yükleme
   sonucunda kaç satırın neden alınmadığı yazar. Şehir alanı boş olan satırlar
   reddedilmez (bir kısım kaynak dosyada bu sütun hiç doldurulmuyor, depo kodu zaten
   Eskişehir'i gösteriyor).
9. **Termin tarihi planlamayı etkilemez.**

**Depolar:** 64, 64-V, 64-P, 74, 74-V, 3, 03, 34, 36, 44 — hepsi anahtar ölçüsüyle.
Yükleme formundaki `64-D DEPO` satırı ayrı bir depo değil, depo 64'ün form üzerindeki
adıdır.

## Modüllerin sipariş havuzu

Her sipariş satırı bir modüle aittir (`RING` / `ROTA` / `IHRACAT`) ve **yalnızca o
modülde görünür**. İç piyasadan yüklenen bir dosya Ring ekranında çıkmaz, Ring
planlaması onu almaz. Hepsini bir arada görmenin tek yeri Raporlama modülüdür; orada
modül sekmeleriyle filtrelenir.

Sipariş dosyası hangi modülün ekranından yüklendiyse o havuza yazılır.

**Sayaçlar ve özetler de modüle bağlıdır.** Gösterge panelindeki "bekleyen sipariş
satırı", raporlardaki aylık/ürün bazlı özet, sevk-Axata takibi ve bekleyenlerin
gerekçesi — hepsi yalnızca bulunduğunuz modülün havuzunu sayar. Ring ekranında iç
piyasa siparişini bekleyen göstermek "planlanması gereken iş var ama listede yok"
izlenimi veriyordu.

## Sefer numarası

`2608D1001` = `26` yıl · `08` ay · `D` belge kodu · `1001` sayaç.
Sayaç her ay ve her belge kodu için `1001`'den başlar. İptal edilen planın numarası
geri kullanılmaz.

| Belge kodu | Nerede |
|---|---|
| `D` | Ring |
| `S` | İç piyasa — FTL |
| `R` | İç piyasa — rutin / parsiyel |
| `K` | İç piyasa — kargo |
| `N` | İhracat — NSC müşterileri |
| `E` | İhracat — Export müşterileri |

İhracatta belge kodu plana değil **müşteriye** bağlıdır; müşteri master datasındaki
"sefer kodu" alanından gelir.

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
