# Excel Veri Formatları

Başlıklar, sahadaki gerçek dosyalara göre belirlendi: ürün master datası için
"Ring Planları" çalışma kitabının **masterdata** sayfası, siparişler için sevk planı /
havuz sipariş sayfaları ve Bekleyen Talep Listesi.

## Başlık ve sayfa eşleştirme

* **Sayfa otomatik bulunur.** Çok sayfalı bir kitap yüklendiğinde sistem bütün
  sayfaların ilk 10 satırını tarar ve aranan tabloyu kendisi bulur. `masterdata`
  sayfası kitabın kaçıncı sayfası olursa olsun bulunur.
* **Başlıklar birebir aynı olmak zorunda değil.** Büyük/küçük harf, Türkçe karakter,
  boşluk ve alt çizgi farkları yok sayılır; ayrıca aşağıdaki tablolarda listelenen
  alternatif başlıklar da tanınır.
* Kolon **sırası** önemli değildir, fazladan kolonlar yok sayılır.
* `#N/A`, `#YOK`, `-` gibi formül hataları **boş** kabul edilir.

## 1. Ürün Master Data

| Kolon başlığı | Zorunlu | Açıklama | Kabul edilen diğer başlıklar |
|---|---|---|---|
| **StokKodu** | Evet | SKU. Sistemdeki benzersiz anahtar. | Stok Kodu, Ürün Kodu, SKU, Malzeme Kodu, Stok No |
| **StokAdi** | Evet | Yükleme formunda görünen ürün adı. | Stok Adı, Ürün Adı, Malzeme Adı |
| **Ürün Grubu** | Evet | PANEL, KOMBİ, KLİMA, TERMOSİFON, AKSESUAR, BACA, ŞOFBEN, ISI POMPASI ... Planlama bu alana göre gruplanır. | Grup, Mal Grubu |
| **Palet içi adet** | Evet | Bir palete kaç adet sığdığı. Palet ölçüsüyle planlanan depolarda (64) kullanılan tek girdi. | Palet İçi Adet, Paletteki Adet |
| **Kamyon yükleme adeti** | Hayır | Bir kamyonu dolduran adet. Kamyon anahtar değeri = 1 / bu sayı. | Kamyon Yükleme Adeti, Kamyon adet |
| **Kamyon palet** | Hayır | Bu üründen bir kamyona sığan palet sayısı (bilgi amaçlı). | — |
| **Tır yükleme adeti** | Hayır | Bir tırı dolduran adet. Tır anahtar değeri = 1 / bu sayı. Anahtar ölçüsüyle planlanan depolarda (74) kullanılır. | Tir yükleme adeti, Tır adet |
| **Tır palet** | Hayır | Bu üründen bir tıra sığan palet sayısı (bilgi amaçlı). | Tir palet |
| **Ağırlık** | Hayır | Birim ağırlık (kg). | Agirlik, Kg |
| **Ürün Desi** | Hayır | Birim desi. | Desi |
| **M3** | Hayır | Birim hacim (m³). | Hacim |
| **Palet En** | Hayır | Palet eni (cm). | — |
| **Palet Boy** | Hayır | Palet boyu (cm). | — |
| **Palet Yükseklik** | Hayır | Palet yüksekliği (cm). | — |
| **Header Kod** | Hayır | Ana ürün ile aksesuarını bağlayan üst kod. Doluysa planlama anahtarı olarak ürün grubunun önüne geçer. | Header Code, Üst Kod |
| **Aktif** | Hayır | E / H. Boş bırakılırsa E kabul edilir. | — |

### Planlama hangi alanı kullanır?

| Depo | Kullanılan alan |
|---|---|
| 64 (palet ölçüsü) | **Palet içi adet** |
| 74 (anahtar ölçüsü) | **Tır yükleme adeti** |

Bir üründe bu alanların üçü de (palet içi adet, kamyon ve tır yükleme adeti) boşsa
ürün kaydedilir ama planlamaya giremez; içe aktarım sonunda uyarı listesinde görünür.

`Header Kod` doluysa o kod altındaki tüm ürünler (ana ürün + aksesuar) her zaman
aynı plandadır ve planlama anahtarı olarak ürün grubunun önüne geçer.

## 2. Siparişler

| Kolon başlığı | Zorunlu | Açıklama | Kabul edilen diğer başlıklar |
|---|---|---|---|
| **Sipariş No** | Evet | Sipariş başlık numarası. | Siparis No, Talep Numarası, Belge No, Order No |
| **Teslimat No** | Evet | Planlamanın bölünemez birimi. Aynı teslimat tek plandadır. | Teslimat, Delivery |
| **StokKodu** | Evet | Master datada tanımlı olmalı; tanımsız ürün planlamaya girmez. | Stok Kodu, Stok No, Ürün Kodu, SKU |
| **StokAdi** | Hayır | Bilgi amaçlı; master data önceliklidir. | Stok Adı, Ürün Adı |
| **Adet** | Evet | Sipariş adedi. Palet ve anahtar hesabı bundan yapılır. | Miktar, Sipariş Miktarı |
| **Depo  Kodu** | Evet | Satır bazlıdır. 64 → palet ölçüsüyle, 74 → anahtar değerle planlanır. | Depo Kodu, Depo, Ambar Kodu |
| **SehirAdi** | Hayır | Yükleme formunun 'İl Adı' sütunu. | Şehir Adı, Sehir Adi, İl, İl Adi |
| **BayiAdi** | Hayır | Yükleme formunun 'Bayii Adı' sütunu. | Bayi Adı, Bayii Adı |
| **AliciFirma** | Hayır | Kaynak dosyada sevk adresi bu sütunda gelir; yükleme formunda adres olarak yazılır. | Alıcı Firma, Alici Firma |
| **SevkAdresi** | Hayır | Kaynak dosyada ilçe bu sütunda gelir; yükleme formunun son adres sütunudur. | Sevk Adresi, İlçe |
| **Not** | Hayır | Teslim şekli (CIF vb.). | Teslim Şekli |
| **Tarih** | Hayır | GG.AA.YYYY | Sipariş Tarihi, Talep Tarihi, Belge Tarihi |
| **Termin Tarihi** | Hayır | GG.AA.YYYY. Planlama önceliğini belirler: eski termin önce planlanır. Boşsa sipariş tarihi kullanılır. | Teslim Tarihi, Sevk Tarihi, Planlama Tarihi, PLANLAMA TARİHİ |
| **Sipariş Satır No** | Hayır | Verilmezse ürün kodu satır anahtarı olarak kullanılır. | Satır No, Kalem No |

### Önemli notlar

* Satır anahtarı **Sipariş No + Teslimat No + ürün kodudur.** Aynı sipariş kalemi
  birden çok teslimata bölünebildiği için teslimat numarası anahtara dahildir.
* Aynı dosyada tekrar eden satırların miktarları toplanır.
* Planlanmış veya tamamlanmış satırlar yeniden yüklemeyle bozulmaz, atlanır.
* **Teslimat numarası atanmamış** satırlar (`BAYİ DEPO` gibi) ve **depo kodu `-1`**
  olan satırlar planlanamaz; hata listesine düşer. Bekleyen Talep Listesi'ndeki
  kayıtlar bu durumdadır — teslimat ve depo ataması yapıldıktan sonra yüklenmelidir.
* Kaynak dosyada `AliciFirma` sütununda adres, `SevkAdresi` sütununda ilçe geliyor.
  Yükleme formu bu sırayı koruyarak yazar.

## 3. Yükleme Formu (çıktı)

Depo operasyonun kullandığı **YÜKLEME FORMLARI (D-RİNG)** düzeni birebir üretilir:

* Sağ üstte `FORM NO : 8101058099.01`
* `SEFER NO` kutusu, `Plan Sevk Tarihi ve Günü`
* Depo/AXATA kutusu: `34-DEPO`, `44-DEPO`, `64-D DEPO`, `64-V DEPO`, `74-DEPO` —
  Axata numarası planın deposuna karşılık gelen satıra yazılır. `64-D DEPO` satırı
  ayrı bir depo değil, **depo 64**'ün form üzerindeki adıdır. Kutuda karşılığı olmayan
  bir depo (03, 36 gibi) için kutuya o deponun satırı eklenir; ayrıca Axata numarası
  formun üst bölümünde ikinci kez yazılır, böylece hiçbir durumda kaybolmaz
* Eksik ürün çıkışı uyarı metni
* Satır tablosu: No · İl Adı · Sipariş No · Belge No · Depo · Ürün Kodu · Ürün Adı ·
  Adet · Bayii Adı · adres · ilçe · Teslimat
* Altta `PLANLAYAN`, `TOPLAM ADET` ve `Sevk Kontrol / Adı Soyadı / İmzası` alanları

Bir günün bütün planları tek çalışma kitabına alt alta yazılır ve her form ayrı
sayfaya basılacak şekilde sayfa sonu konur (yatay, A4).
