# İç Piyasa Sevkiyat Planlama — Analiz (taslak)

Bu doküman, iç piyasa modülü için sözlü olarak aktarılan kuralları kayda geçirir.
Kurallar **2025 yılının tamamı ve 2026'nın 8 ayı** (toplam 273.597 satır, 12.238 plan)
ile doğrulandı. Kod yazımı bundan sonra başlayacak; aşağıdaki sayılar tasarımın
dayanağıdır.

Analizi yeniden üretmek için:

```
python -m scripts.ic_piyasa_analiz "2025 tüm sevkleri.xlsx" "01.2026 Sevk Planları.xlsx" ...
```

Çıktı: `veri/ornek/ic_piyasa_masterdata.xlsx` — Müşteriler, Rota Önerisi, Bölgeler, Özet.

## 0. Veriden çıkan tablo

| Belge kodu | Tip | Plan | Ort. durak | Medyan tır doluluğu | Ort. il | Ort. bayi |
|---|---|---|---|---|---|---|
| `S` | FTL | 5.738 | 3,41 | **%94,4** | 1,55 | 3,16 |
| `R` | Rutin / parsiyel | 1.258 | 28,63 | **%55,3** | 12,95 | 26,75 |
| `K` | Kargo | 288 | 13,03 | ~0 | 6,98 | 12,87 |
| `D` | Ring | 4.301 | 3,69 | %59,5 | 1,01 | 3,69 |
| `A` | Alıcı vasıtası | 217 | 1,06 | %2,6 | 1,02 | 1,04 |
| `B` | Arçelik depo aktarımı (İzmir Kemalpaşa, depo 44) | 230 | 1,04 | %100 | 1,01 | 1,04 |
| `ST` | Stok aktarım | 117 | 1,14 | %68,3 | 1,06 | 1,12 |

**Anlatılan kuralların tamamı veriyle örtüşüyor:**

* Rutin planların medyan doluluğu **%55,3** — "%50–60'ta bırakılır" kuralı birebir.
* Rutinde müşteri başına palet **medyan 2**, müşterilerin **%77'si 3 palet ve altında**
  — 3 palet kuralı doğrulandı (kalan %23 istisna).
* Kargoda müşteri başına desi **medyan 0,7**, **%89'u 10 desinin altında** — 10 desi
  eşiği doğrulandı.
* FTL planlarının **%86'sı 5 durak ve altında** — 5 durak kuralı doğrulandı.
* FTL'de günlük araç sayısı ortalama 14, medyan 12, en yüksek 65; 248 günün yalnızca
  9'unda 35 aracı aşmış. **35 sınırı gerçekçi.**

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
* **Son uğrak noktası** aracın en az **%15 hacmini** kaplamalıdır; aksi hâlde navlun
  mantıklı olmaz. Son uğrak, plandaki en uzak ildir (bkz. `app/domain/iller.py`).
* Uğrama noktası sayısı tır ve kamyonda **en fazla 5**.
* Sipariş yönetimi **bölge bazlıdır**; hangi illerin birlikte rotalanabileceği geçmiş
  planlardan çıkarılacaktır.
* Günlük **en fazla 35 FTL araç** planlanır; aşan hacim sonraki güne aktarılır.
* Planlama **ertesi gün sevk edilecek** şekilde yapılır.

## 4. Müşteri master datası

Geçmiş verilerden **5.146 müşteri** çıkarıldı (`veri/ornek/ic_piyasa_masterdata.xlsx`,
"Müşteriler" sayfası). Alanlar: bayi adı, alıcı firma, il, ilçe, sevk adresi, telefon,
incoterms, tır girişi, sevkiyat tipi kırılımı, toplam adet/desi, son sevk tarihi.

**Tır girişi** geçmişten çıkarıldı ve üç değerli tutuldu:

| Değer | Anlamı | Adet |
|---|---|---|
| `E` | Geçmişte tır ile sevk edilmiş | 1.088 |
| `H` | En az 5 plan yapılmış ama **hiç tır gitmemiş** → tır giremiyor kabul edilir | 604 |
| `?` | Geçmişi az, karar verilemiyor | 3.454 |

`H` çıkanlar mantıklı: *Mall of İstanbul*, *Viaport Yapı Market*, *Şişli Yapı Market*
gibi AVM ve şehir içi mağazalar. `?` olanlar ekrandan tek tek işaretlenecek; sistem
`?` durumundakine tır planlamasını engellemez ama uyarır.

**Not:** Ring (`D`) satırları müşteri master datasına dahil edilmedi. O dosyalarda
`AliciFirma` sütununda adres, `SevkAdresi` sütununda ilçe geliyor; karıştırılırsa
müşteri bilgisi bozuluyor.

## 4b. Bölge ve rota

FTL planlarında birlikte rotalanan iller çıkarıldı: **77 il**, 407 il çifti.
İki il "aynı rotada" sayıldı: en az 8 planda birlikte **ve** küçük olanın planlarının
en az %20'sinde birlikte. Bağlantılı iller birleştirilerek **22 bölge** önerisi üretildi
(`veri/ornek/ic_piyasa_masterdata.xlsx`, "Bölgeler" sayfası).

En sık rotalanan çiftler: İstanbul+Kocaeli (113), İzmir+Manisa (93), Aydın+Denizli (82),
Adana+Hatay (50), Antalya+Isparta (48), Batman+Diyarbakır (47).

Öne çıkan bölgeler:

| Bölge | İller |
|---|---|
| Marmara / Batı Karadeniz | İstanbul, Kocaeli, Sakarya, Tekirdağ, Edirne, Kırklareli, Düzce, Bolu, Zonguldak, Bartın, Karabük, Kastamonu |
| Ege | İzmir, Manisa |
| Güney Marmara | Balıkesir, Bursa, Çanakkale |
| İç Ege | Aydın, Denizli, Muğla, Afyonkarahisar, Uşak |
| Akdeniz Batı | Antalya, Burdur, Isparta |
| Karadeniz | Samsun, Ordu, Giresun, Trabzon, Rize, Sinop, Çorum |

**Uyarı:** Güneydoğu/Doğu illeri tek bir büyük bölgede (29 il) toplandı. Uzun mesafe
rotaları zincirleme birbirine bağlandığı için otomatik ayrım yapılamadı; bu bölgenin
elle bölünmesi gerekiyor.

**Durak sırası** için `app/domain/iller.py` içinde 81 ilin Eskişehir'e yaklaşık
karayolu mesafesi tutuluyor. Bir plandaki duraklar yakından uzağa sıralanır, en uzak il
**son uğrak** olur. Mesafeler yaklaşıktır; amaç kesin navlun değil sıralamadır ve
sıralama ±50 km hatadan etkilenmez. Master data ekranından düzenlenebilir olacak.

**Yükleme tesisleri:** depo `64`, `64-D`, `64-V`, `64-P` ve bayi ortak deposu `-1`
**Eskişehir**'den; `34`, `44`, `74` ve varyantları **Bozüyük**'ten yüklenir. İki tesis
arası ~80 km olduğu için tek mesafe tablosu yeterli.

## 5. Depolar arası ortak yükleme

`64`, `74` ve `-1` depolarından **ortak yüklemeli araç** yapılabilir. Kural:

* Araçta hangi depodan daha az ürün varsa, o depodaki ürünler **başka bir araçla**
  diğer depoya gönderilir.
* Bu aktarma için **ayrı bir plan üretilmez**.
* Yükleme formunda ilgili satırın yanına not düşülür:
  *"64 depoya gönderilmelidir"* / *"74 depoya gönderilmelidir"*.

## 6. Yükleme formu

Format iletildi (`01.09.2026 Tarihli 2. Bölge Yükleme Formları.xlsx`). Günlük ve bölge
bazlı tek bir çalışma kitabı; **her sevkiyat tipi ayrı sayfada**:
`S-FTL Sevk`, `R-Rutin`, `K-KARGO`, `A-ALICI VASITASI`, `D-RİNG`, `M-ARÇELİK`,
`T-SİSTEMSEL`, `KOÇTAŞ`.

Üst blok Ring formuyla aynı: form no, sefer no, plan sevk tarihi, depo/AXATA kutusu
(`34-DEPO`, `44-DEPO`, `64-D DEPO`, `64-V DEPO`, `74-DEPO`) ve uyarı notları
("Paletlerin hazırlandığı sırada etiketlenmesi gerekmektedir",
"BACALAR KOMBİLERİN ÜZERİNE YÜKLENECEKTİR").

Satır tablosu: `No · İl Adi · Sipariş No · Belge No · Depo · Ürün Kodu · Ürün Adi ·
Adet · Bayii Adı · Sevk Adresi · Sevk Adresi · Teslimat` (+ Rutin sayfasında `Axata`).
İlk satırın `No` sütununda araç tipi yazar (`TIR`, `KAMYON`, `FTL RUTİN`).

**Alt blok — Ring formunda olmayan kısım:**

```
Toplam parça sayısı                      333
Araç Yer,Sürücü ve Yükleme yapanın Bilgileri | Sevkiyat Palet Detayı ve Ürün Bilgileri
Araç Tipi     TIR
İl            İZMİR2YER            <- il adı + durak sayısı
İlçe          KARABAĞLAR+BERGAMA   <- ilçeler "+" ile birleşik
Yer Miktarı   2                    <- durak sayısı
Plaka / Şöfor Adı / Telefon
Nak.Firma     OMSAN
Faturalama    DD %25 · VAİLLANT %75   <- marka bazlı fatura yüzdesi
Yükleme yapacak depolar   Kalem   Adet
  64 VAİLLANT               2      800
  64 DEMİRDÖKÜM            20      164
  Bayi Depo                48      333
Planlayan     Mehmet SAKARYA
Sevk Kontrol / Adı Soyadı / İmzası
```

Depolar arası aktarma notu (*"64 depoya gönderilmelidir"*) bu **"Yükleme yapacak
depolar"** bloğunun yanına yazılacak.

## 7. Karara bağlananlar

| # | Konu | Karar |
|---|---|---|
| 1 | `-1` depo | **Bayi ortak deposu**, Eskişehir'de. Sistemde de `-1` kodu ile işlenir. |
| 2 | Rutin aracın kapasitesi | **Anahtar değer**, genelde tır. |
| 3 | Son uğrak alt sınırı | **%15** |
| 4 | Günlük araç sınırı | FTL **35**; rutin/parsiyel **3–4** |
| 5 | Kargo 10 desi eşiği | **Müşterinin toplam siparişi** bazında |
| 6 | Incoterms | Sipariş dosyasında `Not` sütununda: `CIF` / `EXW`. Aynı sütun bazen `" - İLÇE"` biçiminde ilçe taşıyor; ikisi ayrıştırılıyor. |
| 7 | Tır girişi | Geçmişte hiç tır yapılmamış müşteri "tır giremiyor" kabul edilir (en az 5 planı olanlar için) |
| 8 | Müşteri anahtarı | **Bayi adı** ile eşleştirilir; bayi kodlarına ulaşılınca revize edilecek |
| 9 | Yükleme tesisleri | 64 ve -1 Eskişehir; 34, 44, 74 Bozüyük |
| 10 | Doğu/Güneydoğu bölge bölünmesi | Kullanıcı **elle** böler; sistem 29 illik bölgeyi otomatik parçalamaz. |
| 11 | Rutin günlük araç sınırı | **Toplam** 3–4 araç (bölge başına değil). |
| 12 | Kapsam | `M-ARÇELİK`, `T-SİSTEMSEL`, `KOÇTAŞ` ve `B` (Arçelik İzmir Kemalpaşa) **kapsam dışı**. |
| 13 | Marka bazlı fatura yüzdesi | **Anahtar değerdeki paya** göre. Depo kodunun yanında `V` veya `P` olanlar **VAİLLANT**, diğerleri **DEMİRDÖKÜM**. Navlun faturalarının dağıtımında kullanılıyor; yükleme formunda ve plan detayında gösterilir. |
| 14 | "Yer Miktarı" | **Durak sayısı** ile aynı. |
| 15 | Birden fazla Axata numarası | Depo operasyonunun toplama işini kolaylaştırmak için ürünler farklı gruplanarak **bir plana birden çok Axata numarası** verilebiliyor. |

## 8. Hâlâ cevap bekleyenler

| # | Konu |
|---|---|
| 1 | Yükleme formundaki `PROTHERM` satırı: kullanıcı `-P` deposunu da VAİLLANT saydı, ancak formda PROTHERM ayrı bir fatura satırı olarak görünüyor. Ayrı marka olarak ayrılacaksa tek satırlık bir değişiklik (`app/domain/marka.py`). |
| 2 | Bayi ortak deposu (`-1`) sipariş dosyası henüz iletilmedi. |
| 3 | SMTP ayarları (otomatik mail gönderimi). |

## 9. Uygulanan kısımlar

* **Marka payı (13):** `app/domain/marka.py` — depo kodu sonekinden marka, anahtar
  değere göre pay. Plan kaydedilirken `marka_paylari_metni` alanına yazılıyor;
  yükleme formunda `FATURA YÜZDESİ` bloğu, plan detayında "Navlun fatura dağıtımı"
  kartı olarak gösteriliyor. Ring modülünde çalışır durumda, iç piyasa modülünde
  aynı hesap kullanılacak.
* **Çoklu Axata (15):** `AxataNumarasi` tablosu — bir plana virgül/boşluk/noktalı
  virgülle ayrılmış birden çok numara girilebiliyor, her birine açıklama
  yazılabiliyor, tek tek silinebiliyor, mükerrer numara reddediliyor. Yükleme
  formunda birden fazlaysa `AXATA NUMARALARI` listesi yazılıyor.
