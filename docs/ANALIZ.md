# Sevkiyat Planlama Sistemi — Analiz ve Kararlar

Bu doküman iş kurallarının tek referans kaynağıdır. Bir davranış tartışmalı hale
gelirse önce burası güncellenir, sonra kod.

Kurallar iki kaynaktan geliyor: (a) sözlü olarak aktarılan kurallar, (b) 2025 yılının
tamamı (23.540 satır, 2.578 plan) ile Ağustos 2026 örnek planları üzerinde yapılan
inceleme. İkisinin ayrıştığı yerler **"Veriyle doğrulanan"** başlığı altında ayrıca
belirtildi.

## 1. Kapsam

**Faz 1 (bu sürüm):** Ring planlaması — depo 64 ve 74.
**Faz 2:** Tır planlaması (aynı anahtar değer altyapısı, farklı belge kodu).

## 2. Kapasite: anahtar değer

Bütün ring planlamaları **tır bazında, anahtar değerle** yapılır. Depo ayrımı yoktur.

| Ölçü | Üst limit | Alt limit | Kaynağı |
|---|---|---|---|
| Anahtar değer | 1,00 (%100) | 0,90 | `Tır yükleme adeti` |

```
anahtar = Σ ( miktar / tır yükleme adeti )      # 1,00 = araç %100 dolu
palet   = Σ_SKU yukarı yuvarla( plandaki toplam miktar / palet içi adet )
```

**Palet kapasite kısıtı değil, kalite ölçüsüdür.** Aracın dolduğunu anahtar değer
söyler; palet ise yüklemenin ne kadar düzgün olduğunu gösterir. Motor bu ikisini
birlikte gözetir (bkz. §3).

Kapasite soyutlaması (`app/domain/kapasite.py`) palet ölçüsünü de destekler; bir depo
palet bazına dönerse `app/config.py` → `DEPO_PROFILLERI` içinde profili değiştirmek
yeterlidir.

**Depolar:** 64, 64-V, 64-P, 74, 74-V, 3, 03, 34, 36, 44. Yükleme formundaki
`64-D DEPO` satırı ayrı bir depo değil, depo 64'ün form üzerindeki adıdır.

### Alt limit ve esnetme

Alt limiti (0,90) dolduramayan teslimatlar `BEKLEMEDE` kalır; hacim biriktikçe bir
sonraki çalıştırmada plana girerler. Termin tarihine bağlı otomatik esnetme **yoktur**.

Kullanıcı planlama ekranındaki **"Kalanları da planla"** kutusunu işaretlerse alt limit
aranmaz; bu planlar `alt_limit_esnetildi` olarak işaretlenir ve listede **ESNETİLDİ**
rozetiyle görünür. `ESNETME_ASGARI_ORAN` ile bu durumda bile açılmayacak asgari doluluk
tanımlanabilir (varsayılan 0 = sınır yok).

## 3. Planlama anahtarı ve tam palet hedefi

Hedef sırası:

1. **Aracı doldurmak** — anahtar değer üst limite yaklaşmalı.
2. **Tam palet yüklemek** — kırık palet israfı en aza inmeli.
3. **Planı saf tutmak** — mümkün olduğunca tek ürün kodu.

### İki fazlı planlama

* **Faz 1 — SKU saf.** Her ürün kodu kendi içinde paketlenir. Aracı dolduran planlar
  tek ürünlüdür.
* **Faz 2 — grup içi karışık.** Faz 1'den artan teslimatlar, aynı depo ve aynı **ürün
  grubu** içinde birleştirilerek yeniden paketlenir (ör. farklı ölçülerdeki paneller).
  Bu planlar `mix` olarak işaretlenir. Planlama ekranındaki kutu ile kapatılabilir.
* **Farklı ürün grupları otomatik birleşmez.** Onun için "Seçilerek mix plan"
  kutusundan teslimat numaraları elle girilir.

Header kodu tanımlı ürünler ve aksesuar nitelikli gruplar (`AKSESUAR`, `BACA`,
`DİRSEK`) her zaman ana ürünün planındadır; aksesuar tek başına plan açmaz.

### Kırık palet israfı

```
israf = Σ_SKU ( yukarı yuvarla(miktar / palet içi) - miktar / palet içi )
```

Sıfır israf, plandaki her üründen tam palet yüklendiği anlamına gelir. Yerleştirme
kararı **önce israfı düşürür**, sonra aracı en çok dolduran plana yönelir: palet içi
adedi 16 olan bir üründen 13 adetlik bir teslimat varsa, 3 adetlik teslimat o plana
gider ve paleti tamamlar. Değer plana `kirik_palet_israfi` olarak yazılır, listede
israfsız planlar **TAM PALET** rozetiyle görünür.

**Ağustos 2026 verisiyle sonuç:** 89 teslimattan 25 plan; hepsi %90 üzeri dolu,
17'sinde hiç kırık palet yok, toplam israf 7,15 palet. (Önceki palet bazlı kurguda
49 plan çıkıyor ve 27'si neredeyse boş kalıyordu.)

## 4. Diğer planlama kuralları

1. **Teslimat bölünmez.** Bir teslimatın tüm satırları aynı plandadır.
2. **Aksesuar ana ürünle birlikte gider.** Header kod veya aksesuar grubu üzerinden.
3. **Üst limiti tek başına aşan teslimat** kendi istisna planına konur
   (`istisna_asim = True`), plana ve yükleme formuna uyarı yazılır.
4. **Sıralama** büyüklüğe göredir; termin tarihi planlamayı etkilemez.
5. **Yerleştirme** Best-Fit Decreasing'dir; kırık palet israfını en aza indirir.
6. **Ağırlık/tonaj ve rota kısıtı yoktur** — hareket depo içi forklift taşımasıdır.
   Ağırlık yine de hesaplanıp plana yazılır (bilgi amaçlı).

## 5. Sefer numarası

Format: `YY` + `AA` + `D` + `####` → `2608D1001`

**Veriyle doğrulanan:** 2025'te aylık 173–295 plan üretilmiş; belge kodu neredeyse
tamamen `D` (2.566 plan), ayrıca birkaç `S` ve `T`. Sayaç her ay sıfırlanıyor.

Geçmiş verilerde her ay `1001…`, `2001…`, `3001…` gibi birden fazla sayaç bandı
kullanılmış (elle planlama döneminden kalma). **Karar: sistemde tek sayaç kullanılacak.**
Her ay `1001`'den başlar, plan başına bir artar. Aylık hacim 200–300 civarı olduğu için
`1001–9999` aralığı fazlasıyla yeterlidir.

İptal edilen planın numarası geri kullanılmaz; numara akışında boşluk kalması normaldir.

## 6. Plan yaşam döngüsü

```
TASLAK ──> AXATA_BEKLIYOR ──> MAIL_GONDERILDI ──> TAMAMLANDI
   └──────────────┴───────────────────┴──> IPTAL
```

**Axata numarası girilmeden yükleme formu gönderilemez.** Numara, formdaki
depo/AXATA kutusunda planın deposuna karşılık gelen satıra yazılır
(`34-DEPO`, `44-DEPO`, `64-D DEPO`, `64-V DEPO`, `74-DEPO`).

Plan iptal edilince siparişler `BEKLEMEDE`'ye döner.
Sipariş statüleri: `BEKLEMEDE` → `PLANLANDI` → `TAMAMLANDI` (+ `HATALI`).

## 7. Veri kalitesi kuralları

* Bir teslimat **tek planlama anahtarına** ve **tek depoya** ait olmalıdır; değilse
  satırlar `HATALI` statüsüne düşer ve gerekçesiyle listelenir.
* Teslimat numarası atanmamış satırlar (havuz listelerinde `BAYİ DEPO` gibi) ve depo
  kodu `-1` olanlar planlanamaz; hata listesine düşer.
* Aynı dosyada tekrar eden (sipariş + teslimat + ürün) satırların miktarları toplanır.
  Kaynak veride bu durum mevcut.
* Master datada `#N/A` gelen alanlar boş kabul edilir. Kapasite verisi olmayan ürünler
  yine de kaydedilir ama "planlanamaz" uyarısı verilir — Ağustos 2026 master datasında
  2.585 üründen **440'ında** kapasite verisi eksik.

## 8. Açık konular

| # | Konu | Durum |
|---|---|---|
| 1 | Sefer numarası sayacı | **Karar verildi:** tek sayaç, her ay 1001'den |
| 2 | Alt limit esnetmesi | **Karar verildi:** yalnızca manuel "Kalanları da planla" |
| 3 | Kapasite ölçüsü | **Karar verildi:** bütün depolar tır/anahtar değer |
| 4 | Planlama anahtarı | **Karar verildi:** faz 1 SKU saf, faz 2 grup içi karışık |
| 5 | Termin tarihine göre önceliklendirme | **Kaldırıldı** — kullanılmıyor |
| 5 | Mail alıcı listesi ve SMTP bilgileri | **Cevap bekliyor** |
| 6 | Form üzerindeki "PLANLAYAN" alanı — kullanıcı yönetimi gerekli mi? | Şu an plan oluşturan yazılıyor |
| 7 | Esneme eşiği 3 gün doğru mu, ürün grubuna göre değişmeli mi? | Varsayılan 3 gün |
