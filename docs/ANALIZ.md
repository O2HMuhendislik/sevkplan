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

## 2. Kapasite: iki ayrı ölçü

Sahada iki farklı ölçü kullanılıyor ve ikisi de `app/domain/kapasite.py` içindeki tek
soyutlamayla ele alınıyor.

| Depo | Ölçü | Üst limit | Alt limit | Kaynağı |
|---|---|---|---|---|
| 64, 64-D, 64-V, 64-P | **Palet** | 20 | 18 | `Palet içi adet` |
| 74, 74-V, 3, 03, 34, 36, 44 | **Anahtar değer** | 1.00 (%100) | 0.90 | `Tır yükleme adeti` |

```
palet   = yukarı yuvarla( miktar / palet içi adet )      # her SKU için ayrı
anahtar = miktar / tır yükleme adeti                      # 1.0 = araç %100 dolu
```

**Veriyle doğrulanan:**
* Depo 64 planlarının palet dağılımında en yüksek tepe **tam 20 palet** (1.370 planın
  103'ü). "20 palet" kuralı doğrulandı.
* Depo 74 planlarının anahtar değer **medyanı tam 1.000**, palet medyanı 27.
  Bu depoda ölçü palet değil, anahtar değer.
* Kaynak dosyadaki `Kamyon anahtar` sütunu tırın yaklaşık yarısıdır
  (tır yükleme adeti ≈ 2 × kamyon yükleme adeti); depo 74 planları kamyon ölçüsünde
  ≈ 2.0, tır ölçüsünde ≈ 1.0 verir. Sistem tır ölçüsünü kullanır.

**Depo ölçüleri nasıl belirlendi:** 2025'te depo 3 planlarının %95'i, depo 03'ün %95'i,
depo 74'ün %91'i anahtar değeri 1,0 civarında; depo 64/64-V/64-P'nin anahtar medyanı
0,15–0,38 ama palet dağılımının tepesi tam 20. Depo 34, 36 ve 44 için 2025'te yeterli
örnek yok; Ağustos 2026 planlarında anahtar değerleri 1,0 civarında olduğu için anahtar
ölçüsü kabul edildi. Değiştirmek için `app/config.py` → `DEPO_PROFILLERI`.

### Alt limit esnetmesi

2025 verisinde depo 64 planlarının palet medyanı 10,8 — yani pratikte alt limitin çok
altında da plan açılmış. Bunu karşılamak için alt limitin iki esneme yolu var:

1. **Aciliyet (otomatik).** Alt limiti dolduramayan kalıntılar arasında termin tarihine
   `ESNETME_GUN_ESIGI` gün veya daha az kalmış (ya da termini geçmiş) bir teslimat varsa,
   kalanlar alt limite bakılmadan planlanır. Varsayılan eşik **3 gün**.
2. **Kullanıcı isteği (manuel).** Planlama ekranındaki *"Kalanları da planla"* seçeneği
   işaretlenerek alt limit tamamen devre dışı bırakılır.

Her iki durumda da plan `alt_limit_esnetildi` olarak işaretlenir; listede **ESNETİLDİ**
rozetiyle görünür ve plan detayında gerekçesi yazar. Esnetme yapılsa bile
`ESNETME_ASGARI_ORAN` altındaki kalıntılar beklemede bırakılır (varsayılan 0 = sınır yok).

## 3. Planlama anahtarı: bir planın içinde ne aynı kalır?

Ayar: `app/config.py` → `PLANLAMA_SEVIYESI`

| Değer | Anlamı |
|---|---|
| `URUN_GRUBU` *(varsayılan)* | Aynı gruptaki farklı SKU'lar tek planda birleşir |
| `SKU` | Planda tek bir ürün kodu bulunur |

**Veriyle doğrulanan — varsayılanın gerekçesi:** 2025'te üretilen 2.578 planın
sadece 395'inde tek SKU var. 955 PANEL planı birden fazla SKU içeriyor (farklı
ölçülerdeki paneller aynı plana konmuş). Buna karşılık planların 1.668'i **tek ürün
grubundan** oluşuyor; iki gruplu olanların çoğu `AKSESUAR + KOMBİ` gibi ana ürün +
aksesuar eşleşmesi. Yani sahadaki kural SKU değil, **ürün grubu** seviyesinde.

Anahtar belirleme sırası (`app/services/planlama_anahtari.py`):
1. Teslimatta header kodu tanımlı ürün varsa → **header kodu**
2. Yoksa aksesuar nitelikli gruplar (`AKSESUAR`, `BACA`, `DİRSEK`) yok sayılır,
   kalan ana ürünün anahtarı kullanılır
3. Ayara göre ürün grubu ya da ürün kodu

Ürün grupları (master datadan): PANEL, KLİMA, AKSESUAR, BACA, KOMBİ, TANK,
TERMOSİFON, BANYOPAN, KAZAN, ŞOFBEN, BOYLER, VRF, SOLAR, KOLLEKTÖR, ISI POMPASI,
DİRSEK, Header.

## 4. Diğer planlama kuralları

1. **Teslimat bölünmez.** Bir teslimatın tüm satırları aynı plandadır.
2. **Aksesuar ana ürünle birlikte gider.** Header kod veya aksesuar grubu üzerinden.
3. **Üst limiti tek başına aşan teslimat** kendi istisna planına konur
   (`istisna_asim = True`), plana ve yükleme formuna uyarı yazılır.
4. **Sıralama** termin tarihine göredir (yoksa sipariş tarihi); eski olan önce planlanır.
   Alt limit yüzünden dışarıda kalan eski bir teslimat, plandaki aynı büyüklükteki
   daha yeni bir teslimatla yer değiştirir.
5. **Yerleştirme** Best-Fit Decreasing'dir.
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
| 2 | Alt limit esnetmesi | **Karar verildi:** aciliyet (3 gün) + manuel "kalanları planla" |
| 3 | Depo 3, 03, 34, 36, 44 | **Eklendi**, anahtar ölçüsüyle (34/36/44 varsayım) |
| 4 | Planlama anahtarı ürün grubu mu, SKU mu? (veri ürün grubunu gösteriyor) | Varsayılan URUN_GRUBU |
| 5 | Mail alıcı listesi ve SMTP bilgileri | **Cevap bekliyor** |
| 6 | Form üzerindeki "PLANLAYAN" alanı — kullanıcı yönetimi gerekli mi? | Şu an plan oluşturan yazılıyor |
| 7 | Esneme eşiği 3 gün doğru mu, ürün grubuna göre değişmeli mi? | Varsayılan 3 gün |
