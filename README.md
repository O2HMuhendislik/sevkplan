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
| `veri/ornek/urun_masterdata.xlsx` | 2.585 iç piyasa ürünü: ürün grubu, palet içi adet, kamyon ve tır yükleme adetleri, ağırlık, desi, palet ölçüleri |
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
| **İç Piyasa Sevkiyat Planlama** | Hazır — kamyon / tır, FTL / rutin (Ankara-İstanbul-Bursa aktarma) / kargo |
| **İhracat Planlama** | Hazır — tır / konteyner, kara / deniz |
| **Raporlama** | Hazır — modüller arası liste ve plana alınma KPI'ı |
| Araç Talep ve Tedarik | Yakında (sözleşmeli nakliyeciler de erişecek) |
| **Master Data** | Hazır — ürün, müşteri, depo ve sistem tanımları |
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
| **Plan Detayı** | Plan içeriği, Axata no girişi (**depo bazında**), yükleme formu, statü işlemleri, plan geçmişi |
| **Raporlar** | Aylık özet, ürün bazlı doluluk, sevk/Axata takibi, bekleyenlerin gerekçesi, **master datası eksik olduğu için hiç planlanamayanlar**; üç modülde de var |
| **Bekleyenler** | Plana giremeyen sipariş satırları, satır satır gerekçesiyle; üç modülde de var |
| **Manuel Planlama** | Beklemedeki teslimatları filtreleyip **seçerek** planlama; üç modülde de var |
| **Araç İçi Yerleşim** | Planın palet palet yerleşimi: üstten, yandan ve 3B görünüş + yükleme sırası. **İç piyasa ve ihracatta var, ring'de yok** — ring planı tek üründür ve tek noktaya boşaltılır |
| **Sipariş İzleme** (`/raporlama/izleme`) | Sipariş veya teslimat numarasıyla uçtan uca geçmiş sorgulama. Sorgu **bütün modüllerde** aradığı için Raporlama modülünde durur (eski adres `/ring/izleme`) |
| **Veri Yönetimi** | Kurumsal logo yükleme; seçerek veri silme: planlanmamış siparişler, planlar, tümü |
| **Kullanıcılar** | Kullanıcı açma, rol ve modül yetkisi verme, parola sıfırlama |

### Master Data modülü (`/masterdata`)

Bütün modüllerin **ortak verisi** burada durur. Müşteri ve ürün ekranları daha önce
Ring / iç piyasa / ihracat modüllerinin içindeydi; aynı veriye üç ayrı yerden
bakılıyordu. Artık tek yerdeler, eski adresler yönlendiriliyor.

| Ekran | İşlev |
|---|---|
| **Özet** (`/masterdata`) | Kayıt sayıları ve **eksik ürün master datası** dökümü; satıra tıklayınca o eksiği olan ürünler listelenir |
| **Ürünler** | Sütun filtreleri, filtrelenmiş listeyi indirme, toplu yükleme, tekil düzenleme |
| **Müşteriler** | İç piyasa müşterileri: il, ilçe, bölge, tır girişi, cari kod, sevk tipi, cumartesi/e-irsaliye (eski adres `/rota/musteriler`) |
| **İhracat Müşterileri** | Araç tipi, sefer kodu, yükleme tipi, azami tonaj (eski adres `/ihracat/musteriler`) |
| **İhracat Ürünleri** | Sütun filtreleri, filtrelenmiş listeyi indirme, tekil düzenleme; tır/konteyner yükleme adetleri, yeni ve eski hesap (eski adres `/ihracat/urunler`) |
| **Ürün Grupları** | Grup adı değiştirme ve birleştirme; değişiklik bütün ürünlere işler |
| **Ürün Bağları** | Birlikte sevk edilmesi gereken ürünler: klima iç/dış ünite (SET), kombi–baca–montaj seti (AKSESUAR). Bağ **ürün kodu** üzerinden kurulur, teslimat üzerinden değil; eksik kalırsa plan detayında uyarı çıkar |
| **Depolar** | Kod, ad, tesis, yükleme formundaki satır adı ve sırası, Axata açılır mı, parsiyel yapılır mı |
| **Sistem Tanımları** | Planlama sayıları (kargo desi sınırı, rutin palet sınırı, azami durak, rota sapması, günlük araç sınırları) |

#### İndir → doldur → geri yükle

Dışa aktarım, **içe aktarımın tanıdığı başlıkları** kullanır; ikisi de
`app/services/veri_formatlari.py` içindeki aynı alan tanımlarından beslenir. Bu yüzden:

* Ekranda uyguladığınız filtre **indirilen dosyaya da uygulanır** — "palet ölçüsü boş"
  filtresini seçip indirirseniz dosyada yalnızca o 450 ürün olur.
* Ekran ilk 500 kaydı gösterir, **dosya filtrenin tamamını içerir**.
* İndirdiğiniz dosyada eksikleri doldurup aynı dosyayı yükleyebilirsiniz; ayrı bir
  şablon doldurmak gerekmez.
* Dosyada **boş bırakılan sütun mevcut veriyi silmez.** Kısmi dosyalar (yalnızca birkaç
  sütunu olan) yaygın olduğu için bu kural şart: aksi hâlde tek bir kısmi yükleme
  bütün ölçüleri siler ve planlama durur.
* Bir alanı **kasten boşaltmak** için ürünü ekrandan açıp alanı boş bırakın; tekil
  düzenleme formunda boşluk silme anlamına gelir.

#### Cari kod ve sevk tipi listesi

Müşteri master datası geçmiş sevk verisinden üretildiği için **bayi kodu** ve
**tır girişi** çoğunlukla boştu. Sahanın iki sayfalı listesi (CARİ KODLAR +
TESLİMAT TİPİ) Müşteriler ekranından yüklenebiliyor; sayfa adları değil başlıkları
tanınıyor.

Sevk tipi sütunu tek metinde üç bilgi taşıyor ve alanlara ayrılıyor:

| Sevk tipi | Tır girişi | Cumartesi | E-irsaliye |
|---|---|---|---|
| `TIR` | E | var | yok |
| `KAMYON` / `KAMYONET` / `RUTİN` / `SADECE KAMYON` | H | var | yok |
| `TIR-C.TESİ YOK-EİRSALİYE` | E | **yok** | **var** |
| `KAMYON-EİRSALİYE` | H | var | **var** |
| `ZORDA KALIRSAN TIR` | E | var | yok |
| `SOR` | ? | var | yok |

Ham metin `sevk_tipi` alanında da saklanıyor: içinde ileride başka kural çıkabilir
ve ekranda sahanın kendi yazdığı hâli görünsün.

**Eşleştirme yalnızca kesin yapılır.** Üç kademe: ad birebir aynı, yalnız
noktalama/boşluk farkı var, ya da ayırt edici kelimeleri aynı (LTD/ŞTİ/SAN/TİC gibi
unvan ekleri sayılmaz). **Benzerliğe dayalı tahmin yapılmaz:** Türkçe bayi adları
ISI, DEPO, MÜHENDİSLİK gibi ortak kelimeleri paylaşıyor ve oran yanıltıyor —
"AKKAŞ ISI DEPO" ile "ARSE ISI DEPO" %81 benziyor ama farklı bayiler. Yanlış
eşleşme yanlış cari kod ya da yanlış "tır giremez" işareti demek; biri faturaya,
diğeri araç seçimine dokunur.

İki durumda daha yazılmaz:

* **Belirsiz** — ad birden fazla müşteriye uyuyor.
* **Çakışma** — dosyada aynı bayi iki satırda farklı yazılmış ve ikisi de aynı kayda
  düşüyor ("AS MÜHENDİSLİK" bir satırda `KAMYON`, diğerinde `TIR`). Son satırın
  kazanması sessizce yanlış araç kararı üretirdi.

Eşleşmeyenler gerekçesi ve sistemdeki adaylarıyla birlikte Excel'e yazılıyor
(Müşteriler → **Eşleşmeyenler**); oradan tek tek işlenebilir.

Sahadan gelen ilk liste programla birlikte geliyor ve **kurulumda bir kez**
işleniyor; sonraki açılışlarda ekrandan yapılan düzeltmelerin üzerine yazmıyor.

#### Ürün grupları

Ürün grubu planlamanın ikinci fazında kullanılır: aracı dolduramayan artıklar **aynı
grup içinde** birleştirilir. Grup ikiye bölünmüşse bu birleştirme çalışmaz.

**Türkçe büyük harf.** Python'un `str.upper()` metodu Türkçe değildir: `'i'` harfini
`'I'` yapar, oysa Türkçede `i → İ`. Bu yüzden dosyada "Klima" yazan kayıt `KLIMA`,
"KLİMA" yazan kayıt `KLİMA` olarak saklanıyor ve **aynı grup ikiye bölünüyordu**.
Artık `app/domain/metin.py` içindeki `buyuk_harf()` kullanılıyor: "Klima" da "kombi"
de doğru karşılığına (`KLİMA`, `KOMBİ`) gidiyor.

Yazım hatasını (ör. noktasız ı ile "klıma") büyük harf kuralı düzeltemez; onun için
**Ürün Grupları** ekranı var:

* Grup adı değiştirilir; **o gruptaki bütün ürünler** güncellenir.
* Hedef ad zaten varsa iki grup **birleşir** — ikiye bölünmüş grubu toplamanın yolu budur.
* Yalnızca yazımıyla ayrışan gruplar (`KLİMA` ↔ `KLIMA`) ekranın başında uyarı olarak
  listelenir.
* "Gruptan çıkar" ürünleri silmez, grupsuz bırakır.

İç piyasa ve ihracat grupları **ayrıdır**: biri Türkçe (PANEL, KLİMA), diğeri
İngilizce (Radiator, Air Con.). Birleştirilmezler. İhracat adları büyük harfe
çevrilmez, olduğu gibi yazılır.

#### Depo tanımları

Depolar bugüne kadar koda gömülüydü; yeni depo açıldığında yükleme formunun
depo/AXATA kutusuna satır eklemek için kod değiştirmek gerekiyordu. Artık **form
etiketi** ve **sıra** buradan yönetiliyor, form o tanımları okuyor. Tesis bilgisi
ortak yükleme kararında kullanılıyor (Eskişehir / Bozüyük).

**Sınır:** hangi deponun hangi kapasite ölçüsüyle planlanacağı burada değil,
`app/config.py` içindeki `DEPO_PROFILLERI`'ndedir. O bir iş kuralıdır ve gerçek sevk
verisiyle doğrulanmıştır.

#### Sistem tanımları

Sahadan gelen ve değişebilen planlama sayıları ekrandan değiştirilebilir; kayıt yoksa
koddaki varsayılan geçerlidir, "Varsayılana dön" bütün kayıtları siler. Değişiklik
**bundan sonraki planlamalarda** geçerli olur, mevcut planlar etkilenmez.

Ekranın alt bölümü **değiştirilemeyen kuralları** ve dayanaklarını listeler (anahtar
değerin palete yuvarlanmaması, parsiyel depoları, aktarma merkezleri, mesafe modeli).
Bunlar gerçek sevk verisiyle doğrulandı; değişmeleri gerekirse kod ve doğrulama
birlikte güncellenmelidir.

### İç piyasa modülü (`/rota`)

| Ekran | İşlev |
|---|---|
| **Gösterge Paneli** (`/rota`) | Sevkiyat tipi, **araç (kamyon/tır)** ve bölge dağılımı, planlamayı çalıştırma |
| **Siparişler** | Sipariş dosyası yükleme; her müşterinin hangi tiple gideceği ve **gerekçesi**; alınamayan satırlar sebebiyle. Ring ile aynı sipariş havuzu |
| **Planlar** | Tip (FTL/rutin/kargo), **araç (kamyon/tır)**, bölge ve durum filtresi; günlük yükleme formu. Liste "FTL" yerine aracın adını yazar |
| **Plan Detayı** | **Araç (kamyon/tır)**, **yükleme tesisi**, parsiyelde **aktarma merkezi**, rota ve duraklar, son uğrak oranı, ortak yükleme uyarısı, araç/şoför bilgisi, Axata, marka payı , **yerleşim planı**|
| **Manuel Planlama** (`/rota/manuel-plan`) | Teslimat seçerek planlama |
| **Raporlar** | Tip ve bölge bazında plan/durak/doluluk özeti, Excel'e aktarma |

### İhracat modülü (`/ihracat`)

| Ekran | İşlev |
|---|---|
| **Gösterge Paneli** (`/ihracat`) | Ülke ve taşıma modu dağılımı, planlamayı çalıştırma |
| **Siparişler** | Sipariş yükleme; müşteri bazında araç tipi, taşıma modu, hesap sürümü, palet sayısı, kaç araç gerekeceği ve hangi sınırın (hacim/ağırlık) dolduracağı |
| **Planlar** | Durum filtresi, günlük yükleme formu, Excel'e aktarma |
| **Manuel Planlama** (`/ihracat/manuel-plan`) | Teslimat seçerek planlama |
| **Plan Detayı** | Doluluk, palet/desi/ağırlık, yükleme tipi ve müşteri notu, çekici/dorse/mühür, Axata, marka payı |

### Raporlama modülü (`/raporlama`)

| Ekran | İşlev |
|---|---|
| **Özet ve KPI** | Modül bazında sipariş/plan sayıları; siparişin plana alınma süresi dağılımı ve termin gecikme oranı |
| **Tüm Siparişler** | Bütün modüllerin sipariş satırları, modül sekmeleriyle filtrelenir; her satırın plana alınma süresi |
| **Tüm Planlar** | Bütün modüllerin planları, modüle göre filtrelenir |

### Manuel planlama (`/ring|/rota|/ihracat` + `/manuel-plan`)

Otomatik planlama beklemedeki bütün siparişleri değerlendirir. Manuel planlama
ekranında **hangi teslimatların planlanacağını kullanıcı seçer**; motor yalnızca
seçilenler üzerinde çalışır, doluluk / rota / aktarma kuralları aynen işler.

* Seçim **teslimat** bazındadır — teslimat planlamanın bölünemez birimidir, yarısı
  planlanıp yarısı beklemede bırakılamaz. Aynı teslimatın satırları tek satırda toplanır.
* Liste teslimat no, sipariş, bayi, il/ilçe, ürün ve depo üzerinden aranabilir;
  depoya göre daraltılabilir.
* Seçim çubuğu tablo kaydırılırken ekranda kalır: seçili sayısı, plan tarihi,
  "tümünü seç", "seçimi temizle" ve **Seçilenleri planla**.
* **Alt limiti esnet** varsayılan olarak açıktır; az sayıda teslimat seçildiğinde de
  plan üretilir ve plan "alt limit esnetildi" olarak işaretlenir. Kapatılırsa seçim
  aracı dolduramadığında plan çıkmaz.
* Plana giren teslimat listeden düşer; iki kez planlanamaz. Her modül yalnızca kendi
  havuzunu listeler.

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
   **Rota en fazla 100 km sapabilir:** uzaklığa göre sıralamak tek başına yetmiyordu —
   Adana, Hatay, Elazığ ve Mardin hepsi "uzak" olduğu için aynı araca giriyor ama
   araç bir aşağı bir yukarı dolaşıyordu (rota 1.530 km, doğrudan Mardin'e gidiş
   1.162 km). Kural: **rotanın toplam uzunluğu, tesisten son noktaya doğrudan
   gidişten en fazla 100 km uzun olabilir.** Hacim yetse bile sapmayı aşan müşteri o
   araca binmez. İller arası mesafe `app/domain/koordinatlar.py` içindeki il merkezi
   koordinatlarından hesaplanır (kuş uçuşu × 1,25); tahmin, sahadan derlenen
   Eskişehir mesafe tablosunu medyan %6 hatayla yeniden üretiyor. Plan detayında
   rota uzunluğu, doğrudan gidiş ve sapma ayrı ayrı görünür.
6. FTL araçta en fazla **5 durak**; rutinde durak sınırı yoktur (sahada 25-30 durak).
7. **Önce tek tesisten dolu araç; ortak yükleme ikinci tercihtir.** 64 ve bayi ortak
   deposu (-1) **Eskişehir**'dedir, 74/34/44 **Bozüyük**'te — iki ayrı şehir.
   Paketleme iki fazlıdır: *faz 1*'de her tesis kendi içinde paketlenir ve dolan
   araçlar orada kalır; *faz 2*'de yalnızca kendi tesisinden araç dolduramayan
   yükler birleştirilir. Eskiden tek fazda hacim uyduğu için 64 ile 74 aynı araca
   giriyor, depo malı iki şehirden toplamak zorunda kalıyordu. İki tesisten yüklenen
   araç plan listesinde **ORTAK YÜKLEME** rozetiyle işaretlenir.
8. **Parsiyel yalnızca 64, -1 ve 74 depolarından yapılır** ve **64/-1 ile 74 aynı
   araca binmez** — 74 kendi aracıyla gider. Başka depodan (34, 44 ...) parsiyel
   planlanmaz; o teslimatlar gerekçesiyle beklemede kalır. *Doğrulama:* 2025'in 691
   parsiyel aracındaki satırların %99,95'i bu üç depodan çıkmış.
9. **Parsiyelin son noktası aktarma merkezidir.** Yük müşteriye tek tek uğramaz;
   bir aktarma merkezine indirilir, dağıtımı oradan yapılır. Araçlar merkezlere göre
   kurulur ve plan üzerinde son uğrak merkez ilidir: *İstanbul* Marmara/Trakya/Batı
   Karadeniz, *Bursa* Bursa ve batısı/güneyi (Güney Marmara, Ege, Batı Akdeniz),
   *Eskişehir* Eskişehir ve Bilecik (depoların bulunduğu iller — yük taşınmaz,
   yerinde dağıtılır), *Ankara* Ankara ve doğusu, yani kalan her yer. Tablo
   `app/domain/aktarma.py` içindedir; tarife değişirse yalnızca orası güncellenir.
10. **Rutin araç %50-60 dolulukta bırakılır.** Kapasite ölçüsü FTL ile aynıdır:
   ham anahtar değer. Sevkiyat tipi ölçüyü değiştirmez.
11. **Günlük sınır:** 35 FTL, 4 rutin. Aşan hacim gerekçesiyle beklemede kalır ve
   sonraki gün planlanır. Sınır, o gün daha önce üretilmiş planları da sayar.
12. **Bölünmez olan teslimattır, müşteri değil.** Bir aracı aşan müşterinin teslimatları
   birden çok araca dağıtılır; tek başına aracı aşan teslimat istisna planına gider.
13. **Ortak yüklemede aktarma notu:** araç, hacmin çoğunu taşıyan depodan yüklenir;
    diğer **tesisteki** malın satırına yükleme formunda *"… depoya gönderilmelidir"*
    notu düşülür. Not yalnızca Eskişehir (64, -1) ile Bozüyük (74, 34 ...) arasında
    yazılır — 64 ile -1 aynı lokasyondadır, aralarında aktarma yoktur. Yükleme
    deposu kutusu da o tesisteki depoların hepsini gösterir (*"64 + -1"*).
14. **Kargo günde tek plandır.** 10 desinin altındaki bütün siparişler tek kargo
    listesinde toplanır; her müşteriye ayrı sefer numarası açılmaz.
15. **Bölünebilir (-1) teslimat oransal bölünür.** Her araca teslimattaki bütün
    ürünlerden aynı oranda konur; şofben bir araca, bacası başka araca düşmez. (Ürün
    master datasında header kod alanı boş olduğu için aksesuarı ana ürüne bağlayan
    başka bir bilgi yok; oransal bölme bu bağı kendiliğinden korur.) Kesim noktası
    tam palete indirilir (depoda palet kırılmasın diye); payı bir paletin altında
    kalan küçük kalemler bölünmez.
16. **Tır girişi bilinmeyen müşteri** (alan boş) tır varsayılır; plan detayında ve
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

## Araç içi yerleşim (istif) planı

İç piyasa ve ihracat plan detayındaki **Yerleşim planı** düğmesi aracın üstten
görünüşünü çizer: hangi palet nereye, hangi sırayla yüklenecek. Depo bugüne kadar
yalnızca satır listesini görüyordu; malın araca hangi sırayla konulacağı yükleyicinin
kafasındaydı.

**Ring modülünde bu ekran yoktur.** Ring planı tek üründen ve tek depo çıkışından
oluşur; araç tek noktaya boşaltılır, durak sırası diye bir şey yoktur. Palet palet
yerleşim çizmenin depoya kattığı bir bilgi olmuyordu.

**Ters rota sırası.** En son uğranacak durağın malı en dibe (kabin tarafına), ilk
durağın malı kapıya konur. Aksi hâlde ilk durakta bütün aracı boşaltmak gerekir.
Ekrandaki numaralar yükleme sırasıdır; durak sırası plan detayındakinin aynısıdır.
Ekranın **Yükleme sırası** tablosu bu numaraları ürün, palet ve durak bilgisiyle
birlikte listeler — depo hangi ürünü en başta yükleyeceğini oradan okur.

**Üç görünüş.** Üstten (x-y), yandan (x-z) ve 3 boyutlu; üçü de aynı yerleşimden
çizilir, çelişemezler. 3B görünüş **saf CSS 3B dönüşümleriyle** yapılır, harici
kütüphane yüklenmez: program şirket içi bir sunucuda çalışıyor ve internet
erişimine bağlı olmamalı. Sürükleyerek çevrilir, tekerlekle yakınlaştırılır.

**Her kutu tek bir palettir.** Palet, master datadaki **eni ve boyu** kadar yer
kaplar; ölçüler modülün **kendi** master datasından okunur — ihracat SKU'ları iç
piyasa ürün tablosunda yok, yanlış tablodan arayınca bütün miktar tek palet
sayılıyordu. İhracat master datasındaki `EN / BOY / YÜKSEKLİK` sütunları paletin
ölçüsüdür (palet içi adet 12 olan üründe 90×120×228 dolu paletin ölçüsü).
Palet aracın enine daha çok sığan yönde çevrilir (depo da öyle yapıyor). Bir sıraya
**aynı durağın** paletleri yan yana girer, ürünleri farklı olabilir — tek paletlik
kalemler sıranın kalanını boş bırakmasın diye. Durak karışmaz: sıra bir bütün olarak
iner, dipteki sıraya öndekiler boşaltılmadan ulaşılamaz. Ölçüsü tanımsız ürün için
standart Euro palet (80×120) varsayılır.

Zeminde kalan boşluk **gerçektir**: o sıranın eni tam dolmamıştır. Ekrandaki
**zemin kaplama** yüzdesi kaplanan alanı ölçer, kullanılan uzunluğu değil.

Araç iç ölçüleri tahmin değil, şirketin kendi verisinden türetildi:

| Araç | Zemin | Doğrulama |
|---|---|---|
| Tır | 1360 × 245 cm | 80×120 palet → 33, 100×120 → 26 (master datanın "tır palet" sütunu) |
| Kamyon | 700 × 245 cm | Aynı ürünlerde 17 ve 14 — tırın tam yarısı |

**Kapasite kararı bu çizimde değil, anahtar değerdedir.** Çizim fiziki yerleşimi
gösterir; ikisi aynı şeyi ölçmez. Anahtar değeri 1,00 olan bir araçta palet gözü
sayısı zeminden fazla çıkar (3 adetlik bir kalem de bir palet yapar) — fazlası üst
kata konur, oraya da sığmayan kalırsa gerekçesiyle listelenir. 30.09.2025'in gerçek
verisinde 30 FTL aracın 1.308 paletinin **729'u zeminde, 579'u üst katta**;
**129'u** (%10) yerleştirilemiyor. Zemin kaplama medyanı **%83**.

### Üst kat (istif)

Doluluğu 1,00 olan bir araçta palet gözü sayısı zeminden fazla çıkar: 3 adetlik bir
kalem de bir palet yapar ama depo onu yere ayrı bir göz olarak koymaz, başka paletin
üstüne alır. Yerleştirme iki kuralla çalışır:

* **Yükseklik.** Yığın aracın iç yüksekliğini aşamaz. Kırık palet **tam boy
  sayılmaz**: 16'lık palette 3 ürün varsa yığın 3/16'sı kadar yükselir (alt sınır
  palet tahtası, 15 cm). Tam boy sayılsaydı hiçbir kırık palet istiflenemez ve dolu
  bir araçta paletlerin beşte biri "yerleştirilemedi" görünürdü.
* **Boşaltma sırası.** Üstteki palet, tabanından **önce ya da onunla aynı** durakta
  inmelidir. Aksi hâlde alttaki malı almak için üstündekini indirip tekrar yüklemek
  gerekir.

Model bilerek temkinlidir: paletleri kesmez, döndürmekten başka bir şey yapmaz ve
yalnızca tam palet üstüne tam palet koyar.

Ekran ağırlığın ön/arka dağılımını da gösterir (dingil yükü) ve yazdırılabilir.

## Anahtar değer neden palete yuvarlanmaz

Anahtar değer, aracın kapasite ölçüsüdür:

```
anahtar değer = Σ ( miktar / o aracın yükleme adeti )      1,00 = araç %100 dolu
```

Bir dönem bu ölçü **palete yukarı yuvarlanıyordu**: "kırık palet araçta yarım yer
kaplamaz, tam bir palet gözü kaplar" varsayımıyla miktar önce palete çıkarılıyordu.
Varsayım sahada tutmadı ve ölçüyü sistematik olarak şişirdi.

**Kanıt 1 — şirketin kendi dosyası.** `2025 tüm sevkleri` dosyası anahtar değeri
satır bazında taşıyor (birim / kamyon / tır sütunları). Orada yuvarlama yok: satırın
değeri birim değerin tam olarak `adet` katı (7.240 aracın tamamında oran 1,0).

**Kanıt 2 — 2.048 gerçek tır.** Master datayla birebir eşleşen gerçek tırlarda:

| Ölçü | Medyan | %25 | %75 | 1,00'ı aşan |
|---|---|---|---|---|
| Şirketin kendi anahtar değeri | 0,995 | 0,959 | 1,021 | %40,9 |
| **Ham (yuvarlamasız) — bugünkü ölçü** | **1,000** | 0,967 | 1,034 | %48,6 |
| Palete yuvarlanmış — eski ölçü | 1,263 | 1,122 | 1,500 | **%94,6** |

Yuvarlanmış ölçüyle gerçek tırların %94,6'sı "araca sığmıyor" görünüyordu; ham ölçü
gerçek araçların medyanını tam 1,000 veriyor.

**Kanıt 3 — sahadan gelen 2609S1026 planı.** Bayi ortak deposundan (-1) çıkan
18 SKU'luk yük: sistem **%98,43** yazıyordu, araç gerçekte **%35,7** doluydu.
Sebep iki katmanlı:

* -1 siparişlerinde her satır kendi teslimatını oluşturuyor. Aynı ürünün dört ayrı
  satırı dört ayrı palet sayılıyordu: 28 adet atık gaz borusu 4 × 77 = 308 adet gibi
  ölçülüyordu.
* Yuvarlama sonrası kalan kısımda da her SKU bir tam palet sayılıyordu; 1, 3, 5
  adetlik kalemler tam palet oluyordu.

**Etki — 30.09.2025'in gerçek iç piyasa siparişleriyle** (2.453 satır, 299 müşteri):

| | Üretilen FTL aracı | Araçların **gerçek** doluluğu (medyan) | Gerçekte %75 altında |
|---|---|---|---|
| Eski ölçü | 35 | %51,4 | 30 / 35 |
| **Bugünkü ölçü** | **28** | **%99,4** | **0 / 28** |

Aynı yük 7 araç daha az yer tutuyor ve çıkan araçların hepsi gerçekten dolu.

Kırık palet hâlâ istenmeyen bir şeydir; ama bu bir **kapasite** kısıtı değil, bir
**kalite** ölçüsüdür: `PaletIsrafi` ile ölçülür ve yerleştirme kararında
gözetilir. Bölünebilir teslimatın kesim noktası da tam palete indirilir. Kod
`app/domain/planlama.py` içindeki `AnahtarBirimi` sınıfındadır.

İhracat modülü bu ölçüyü hiç kullanmadı; orada doluluk `Hesaplama.xlsx`'in kendi
formülüyle (miktar / yükleme adeti, yuvarlamasız) hesaplanır.

## Ring planlama kuralları (özet)

1. Teslimat numaraları **bölünmez**; bir teslimatın tüm satırları aynı plandadır.
2. **Kapasite anahtar değerdir; palete yuvarlanmaz.**

   ```
   anahtar değer = Σ ( miktar / o aracın yükleme adeti )      1,00 = araç %100 dolu
   ```

   Bütün depolar tır bazında planlanır; alt limit **0,90**. Ayrıntı ve doğrulama
   için aşağıdaki "Anahtar değer neden palete yuvarlanmaz" bölümüne bakın.
3. **Hedef tam palet.** Palet sayısı plan bazında hesaplanır: aynı ürünün farklı
   teslimatlardaki miktarları önce toplanır, sonra palete yuvarlanır. Palet içi adedi
   16 olan bir üründen 13 + 3 adet, iki kırık palet değil **tek dolu palet**tir.
   Yerleştirme, kırık palet israfını en aza indirecek plana yönelir — ama bu bir
   **kalite** ölçüsüdür, kapasiteye girmez.
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

### Bayi adı sütunu

Sahadaki sipariş dosyalarında bu sütunun başlığı çoğu zaman yalnızca **`BAYI`**;
`BayiAdi` / `Bayi Adı` / `Bayii Adı` / `Müşteri Adı` yazımları da tanınır. Başlık
tanınmazsa sütun hiç okunmaz ve bayi adı plan detayında, yükleme formunda `—` görünür.
Bayi adı gerçekten boş gelirse sırayla ikinci `Not` sütunu, alıcı firma ve açık adres
denenir (bkz. `SiparisSatiri.bayi_gosterimi`).

Aynı dosya yeniden yüklendiğinde **planlanmış satırlar bozulmaz**: miktar, depo, durum
ve plan bağı korunur. Yalnızca tanıtıcı alanlar (bayi adı, alıcı firma, adres, ilçe)
dosyadaki dolu değerle tazelenir — böylece yanlış okunmuş bir bayi adı, satır zaten
planlandığı için sonsuza kadar `—` kalmaz. Dosyada boş gelen sütun sistemdeki dolu
bilgiyi silmez.

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
imza alanları. **Numara girilmeden plan gönderildi olarak işaretlenemez.** Bir günün
bütün planları tek dosyaya, her biri ayrı sayfaya basılacak şekilde alt alta
yazılabilir.

### Axata iş emri hangi depoya ait?

Bir planda birden fazla depo olabiliyor (ör. 64 + 74) ve **her depo kendi Axata iş
emrini açıyor**. Numara depoya bağlanmazsa yükleme formunda hangi satıra yazılacağı
bilinemez; depo yanlış iş emriyle toplama yapar.

* Planda birden çok depo varsa Axata girişinde **depo seçimi zorunludur**. Plan
  detayı depoları listeler, seçilmeden numara kaydedilmez.
* Planda olmayan bir depo seçilemez — numara formda hiçbir satıra düşmez ve sessizce
  kaybolurdu.
* Tek depolu planda (Ring, çoğu ihracat planı) depo seçimi istenmez; numara "tüm
  depolar" olarak kaydedilir ve planın kendi depo satırına yazılır. Eski kayıtlar da
  böyle davranır.
* Yükleme formunda her numara **yalnızca kendi deposunun satırına** basılır. Satır
  tablosundaki Axata sütunu da satırın kendi deposunun numarasını gösterir.
* Bir depoya numara girilmemişse plan detayında uyarı çıkar; formda o deponun satırı
  boş kalır.
* Bayi ortak deposu (-1) hariçtir: orası ayrı bir ERP, Axata iş emri açılmaz.

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
