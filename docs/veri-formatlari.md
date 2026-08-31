# Excel Veri Formatları

Sistem iki Excel dosyası okur: **ürün master datası** ve **siparişler**.
Her ikisinin de hazır şablonu uygulama içinden indirilebilir
(`Master Data > Şablonu indir`, `Siparişler > Şablonu indir`) ve
`veri/ornek/` klasöründe hazır durur.

## Başlık eşleştirme nasıl çalışır?

Kolon başlıkları birebir aynı yazılmak zorunda değildir. Karşılaştırma yapılırken
büyük/küçük harf, Türkçe karakter, boşluk ve alt çizgi farkları yok sayılır. Ayrıca
her kolonun kabul edilen alternatif başlıkları vardır (aşağıdaki tablolarda son sütun).
Örneğin `Ürün Kodu`, `ÜRÜN KODU`, `urun_kodu`, `SKU` ve `Malzeme Kodu` aynı kolondur.

Kolon **sırası** önemli değildir; fazladan kolonlar yok sayılır. Zorunlu bir kolon
bulunamazsa dosya hiç işlenmez ve hangi kolonun eksik olduğu bildirilir.

## 1. Ürün Master Data

Dosya: `veri/ornek/urun_masterdata_sablonu.xlsx`

| Kolon başlığı | Zorunlu | Açıklama | Kabul edilen diğer başlıklar |
|---|---|---|---|
| **Ürün Kodu** | Evet | SKU. Sistemdeki benzersiz anahtar. | SKU, Malzeme Kodu, Stok Kodu, Material |
| **Ürün Adı** | Evet | Yükleme formunda görünecek isim. | Malzeme Adı, Stok Adı, Tanım |
| **Ürün Grubu** | Evet | Kombi, Radyatör, Termosifon, Klima, Şofben, Isı Pompası ... | Grup, Mal Grubu |
| **Palet İçi Adet** | Evet | Bir palete kaç adet sığdığı. Palet hesabının tek girdisi. Tam sayı, > 0. | Paletteki Adet, Palet Adedi, Palet Kapasitesi |
| **Header Kod** | Hayır | Ana ürün ve aksesuarını bağlayan üst kod. Aynı header kodlu ürünler her zaman aynı plana girer. Header sistemi kullanılmıyorsa boş bırakın. | Header Code, Üst Kod, Ana Kod |
| **Aksesuar mı** | Hayır | E / H. Header kod altındaki aksesuar kalemleri için E. | Aksesuar, Aksesuar mi |
| **Aktif** | Hayır | E / H. Boş bırakılırsa E kabul edilir. | — |

### Önemli notlar

* **Palet İçi Adet** planlamanın tek sayısal girdisidir. Bir teslimatın palet sayısı
  `yukarı yuvarla(miktar / palet içi adet)` ile bulunur; kırık palet bir tam palet sayılır.
* **Header Kod** doldurulduğunda o kod altındaki tüm ürünler (ana ürün + aksesuarlar)
  aynı planda kalır. Header sistemi kullanmayan ürünlerde boş bırakın.
* Aynı ürün kodu tekrar yüklenirse kayıt **güncellenir**, mükerrer oluşmaz.
* Pasif (`Aktif = H`) ürün içeren teslimatlar planlamaya alınmaz, hata listesine düşer.

## 2. Siparişler

Dosya: `veri/ornek/siparis_sablonu.xlsx`

| Kolon başlığı | Zorunlu | Açıklama | Kabul edilen diğer başlıklar |
|---|---|---|---|
| **Sipariş No** | Evet | Sipariş başlık numarası. | Siparis No, Order No, Belge No |
| **Sipariş Satır No** | Evet | Sipariş içindeki satır sırası. Sipariş no ile birlikte benzersiz olmalı; aynı dosya iki kez yüklenirse mükerrer kayıt oluşmaz. | Satır No, Kalem No, Pozisyon |
| **Teslimat No** | Evet | Planlamanın bölünemez birimi. Aynı teslimat tek plandadır. | Teslimat, Delivery, Sevkiyat No |
| **Müşteri Kodu** | Hayır | Raporlama için. | Cari Kodu, Müşteri No |
| **Müşteri Adı** | Hayır | Yükleme formunda görünür. | Cari Adı, Müşteri Ünvanı |
| **Ürün Kodu** | Evet | Master datada tanımlı olmalı; tanımsız ürün planlamaya girmez. | SKU, Malzeme Kodu, Stok Kodu |
| **Ürün Adı** | Hayır | Bilgi amaçlı; master data önceliklidir. | Malzeme Adı, Stok Adı |
| **Miktar** | Evet | Sipariş adedi. Palet hesabı bundan yapılır. | Adet, Sipariş Miktarı, Kalan Miktar |
| **Birim** | Hayır | Varsayılan ADET. | Birim Kodu, UOM |
| **Depo Kodu** | Evet | Satır bazlıdır. 64 ise Ring planlaması, değilse Faz 2 (tır) kapsamındadır. | Depo, Ambar Kodu, Depo No |
| **Sipariş Tarihi** | Hayır | GG.AA.YYYY | Belge Tarihi |
| **Termin Tarihi** | Hayır | GG.AA.YYYY. Planlama önceliğini belirler: eski termin önce planlanır. | Teslim Tarihi, Sevk Tarihi, İstenen Tarih |

### Önemli notlar

* **Sipariş No + Sipariş Satır No** birlikte benzersizdir. Aynı dosya iki kez
  yüklenirse mükerrer kayıt oluşmaz; mevcut satır güncellenir.
* Planlanmış veya tamamlanmış satırlar yeniden yüklemeyle **bozulmaz**, atlanır.
* Bir **teslimat numarası** yalnızca tek ürün içerebilir. İçinde birden fazla ürün
  bulunan teslimatın tüm satırları `HATALI` statüsüne düşer ve Siparişler ekranındaki
  HATALI sekmesinde gerekçesiyle listelenir. Header kod ile bağlı ana ürün + aksesuar
  bu kuralın istisnasıdır, tek ürün sayılır.
* **Depo Kodu** satır bazlıdır. `64` olan satırlar Ring planlamasına girer; diğerleri
  Faz 2 (tır planlaması) kapsamındadır ve şimdilik beklemede kalır.
* **Termin Tarihi** planlama önceliğini belirler: eski terminli teslimatlar önce planlanır.
  Boşsa sipariş tarihi kullanılır.
* Tarih formatı `GG.AA.YYYY` (Excel'in gerçek tarih hücreleri de okunur).

## 3. Yükleme Formu (çıktı)

`app/services/yukleme_formu.py` içindeki düzen **geçicidir** — nihai form formatı
iletildiğinde yalnızca bu modül değişecektir. Formun şu an taşıdığı bilgiler:

* Üst bilgi: sefer no, **Axata iş emri no**, plan tarihi, depo kodu, toplam palet,
  doluluk yüzdesi, teslimat sayısı, ürün kodları
* Satırlar: teslimat no, sipariş no/satır, müşteri, ürün kodu, ürün adı, miktar, birim, termin
* Alt bilgi: toplam palet ve imza alanları (Hazırlayan / Depo Sorumlusu / Forklift Op.)

Axata numarası girilmeden plan "gönderildi" olarak işaretlenemez.
