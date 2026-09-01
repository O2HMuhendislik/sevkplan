# İç Piyasa Sevkiyat Planlama — Analiz (taslak)

Bu doküman, iç piyasa modülü için sözlü olarak aktarılan kuralları kayda geçirir.
**Henüz kod yazılmadı**; 2025–2026 FTL planlama verileri geldiğinde kurallar veriyle
doğrulanıp (Ring modülünde olduğu gibi) hayata geçirilecek.

## 1. Sevkiyat tipleri

İç piyasa siparişleri üç şekilde planlanır. Planlama ekranında tip seçilir.

| Tip | Belge kodu | Ne zaman |
|---|---|---|
| **FTL** (tam araç) | `S` | Bölgeye tam araç oluşacak hacim varsa |
| **Rutin / Parsiyel** | `R` | Müşterinin toplam siparişi **en çok 3 palet** ise |
| **Kargo** | — | FTL veya parsiyel çıkacak hacim yoksa; 10 desi altı siparişler ya da Incoterms **EXW** olanlar (müşteri ödemeli) |

Sefer numarası mantığı Ring ile aynıdır, yalnızca belge kodu değişir:
`2609S1001`, `2609R1001`.

## 2. Rutin (parsiyel) planlama

* **3 palet kuralı müşteri bazındadır**, ürün grubuna bakılmaz: bir müşterinin o günkü
  *tüm* siparişi 3 paleti aşmıyorsa rutin ile gönderilebilir.
* Aynı bölgeye FTL araç oluşuyorsa ve müşteri o rotadaysa, müşteri rutin yerine **FTL
  araca** da eklenebilir.
* Rutinde araç doluluğu gözetilir ama **%100 hedeflenmez**: karışık palet ve çok sayıda
  müşteri olduğu için araç **%50–60 dolulukta** bırakılır.

## 3. FTL planlama

* Bir araçta **birden fazla uğrama noktası** olabilir.
* **Son uğrak noktası** aracın en az **%25–30 hacmini** kaplamalıdır; aksi hâlde navlun
  mantıklı olmaz.
* Uğrama noktası sayısı tır ve kamyonda **en fazla 5**.
* Sipariş yönetimi **bölge bazlıdır**; hangi illerin birlikte rotalanabileceği geçmiş
  planlardan çıkarılacaktır.
* Günlük **en fazla 35 FTL araç** planlanır; aşan hacim sonraki güne aktarılır.
* Planlama **ertesi gün sevk edilecek** şekilde yapılır.

## 4. Müşteri master datası

Ürün master datası gibi bir de **müşteri master datası** tutulacak. Geçmiş planlardan
çıkarılacak ve ekrandan düzenlenebilecek alanlar:

* Müşteri kodu, ünvan, bayi adı
* İl, ilçe, sevk adresi
* Bölge
* **Tır girişi var mı?** — fiziki adres sebebiyle tır giremeyen müşterilere yalnızca
  **kamyon** ya da **parsiyel** planlaması yapılır
* Incoterms (CIF / EXW …)

## 5. Depolar arası ortak yükleme

`64`, `74` ve `-1` depolarından **ortak yüklemeli araç** yapılabilir. Kural:

* Araçta hangi depodan daha az ürün varsa, o depodaki ürünler **başka bir araçla**
  diğer depoya gönderilir.
* Bu aktarma için **ayrı bir plan üretilmez**.
* Yükleme formunda ilgili satırın yanına not düşülür:
  *"64 depoya gönderilmelidir"* / *"74 depoya gönderilmelidir"*.

## 6. Yükleme formu

Her sevkiyat tipi için yükleme formu üretilir. Ring formundan farkı: forma **iller,
ilçeler ve durak sayısı** da yazılır. Nihai format iletilecek.

## 7. Cevap bekleyen konular

| # | Konu |
|---|---|
| 1 | **2025–2026 iç piyasa FTL planlama dosyaları** — rotalanabilir iller, bölge tanımları ve müşteri master datası buradan çıkarılacak |
| 2 | **İç piyasa yükleme formu formatı** |
| 3 | `-1` depo ne anlama geliyor? (Bekleyen Talep Listesi'nde depo ataması yapılmamış satırlar `-1` ile geliyordu — burada gerçek bir depo olarak mı kullanılıyor?) |
| 4 | Rutin aracın kapasitesi neye göre ölçülür — palet mi, anahtar değer mi? Rutin araç tipi kamyon mu, ayrı bir araç mı? |
| 5 | Son uğrak için alt sınır %25 mi %30 mu? Hacim ölçüsü anahtar değer mi? |
| 6 | Günlük 35 araç sınırı yalnızca FTL için mi, rutin ve kargo dahil mi? |
| 7 | Kargo eşiği olan 10 desi: sipariş satırı bazında mı, müşterinin toplam siparişi bazında mı? |
| 8 | Incoterms bilgisi sipariş dosyasında hangi kolonda geliyor? (Ring dosyasında "Not" sütununda CIF görünüyordu) |
| 9 | Tır girişi olmayan müşteriler bilgisi geçmiş veride var mı, yoksa elle mi işaretlenecek? |
| 10 | Bölge–il eşleşmesi sabit mi, mevsimsel/duruma göre değişiyor mu? |
