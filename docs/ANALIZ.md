# Sevkiyat Planlama Sistemi — Faz 1 Analiz ve Kararlar

Bu doküman, sistemin iş kurallarının tek referans kaynağıdır. Kodda bir davranış
tartışmalı hale gelirse önce burası güncellenir, sonra kod.

## 1. Kapsam

**Faz 1 (bu repo):** Depo kodu `64` olan sipariş satırları için **Ring planlaması**
— 20 paletlik sevkiyat planları.

**Faz 2 (sonra):** Depo kodu `64` dışındaki siparişler için **tır bazlı planlama**
(palet değil, "anahtar değer" %100 dolulukla).

Faz 2'yi bugünden karşılamak için kapasite soyutlaması parametrik kuruldu:
`app/domain/kapasite.py` içinde her plan tipi kendi kapasite ölçüsünü tanımlar.
Ring için ölçü = palet, kapasite = 20. Tır için ölçü = anahtar değer, kapasite = 100.
Planlama motoru ölçünün ne olduğunu bilmez, sadece "birim" ile çalışır.

## 2. Temel kavramlar

| Kavram | Tanım |
|---|---|
| Sipariş satırı | Excel'den gelen en küçük kayıt. Depo kodu **satır bazındadır**. |
| Teslimat (`teslimat_no`) | Planlamanın atomik birimi. Bölünemez. |
| SKU (`urun_kodu`) | Planlama, SKU bazında gruplanır. |
| Header code | Ana ürün + aksesuarını bağlayan üst kod. Aynı planda olmak zorundadır. |
| Planlama anahtarı | `header_kod` varsa o, yoksa `urun_kodu`. Motor bu alana göre gruplar. |
| Sefer no | Plan kimliği. Format: `YYAAD####` (örn. `2608D1001`). |
| Axata no | WMS iş emri numarası. Yükleme formuna işlenir, mail öncesi zorunludur. |

## 3. Faz 1 iş kuralları (kararlaştırılmış)

1. **Teslimat bölünemez.** Bir teslimatın tüm satırları aynı plandadır.
2. **Bir planda tek SKU** bulunur (header code istisnası hariç).
   Mix plan sadece manuel tetiklemeyle yapılır (Faz 1'de kapsam dışı, altyapısı hazır).
3. **Header code'lu ürünler:** ana ürün ve aksesuarı aynı plandadır. Planlama
   anahtarı header code olduğu için bu doğal olarak sağlanır.
4. **Kapasite:** üst sınır 20 palet, alt sınır 18 palet.
   18 paletin altında kalan teslimatlar planlanmaz, `BEKLEMEDE` statüsünde kalır.
5. **İstisna:** tek başına 20 paletten büyük bir teslimat, kendi planına tek başına
   yerleştirilir ve plan `istisna_asim = True` olarak işaretlenir.
6. **Ağırlık / tonaj limiti yoktur.** Hareket depo içi forklift taşımasıdır.
7. **Rota / coğrafi kısıt yoktur.** Aynı sebeple.
8. **Yalnızca tek ürün içeren teslimatlar** sisteme yüklenir. Çok ürünlü teslimat
   gelirse plana alınmaz, `HATALI` statüsüyle hata listesine düşer ve raporlanır.

### Palet hesabı
```
teslimat_palet = ceil( teslimattaki toplam miktar / urun.palet_ici_adet )
```
Kırık palet 1 tam palet sayılır (fiziksel gerçeklik: yarım palet de bir göz kaplar).

### Planlama sırası
Aynı grup içindeki teslimatlar **termin tarihi eskiden yeniye** sıralanır; böylece
bekleyen eski siparişler önce planlanır. Termin tarihi yoksa sipariş tarihi kullanılır.

### Yerleştirme algoritması
`Best-Fit Decreasing`: teslimatlar palet adedine göre büyükten küçüğe sıralanır,
her biri en az boşluk bırakacak plana konur. Kapasite dolunca yeni plan açılır.
Sonuçta 18 paletin altında kalan planlar dağıtılır, içindeki teslimatlar
`BEKLEMEDE`'ye döner.

## 4. Sefer numarası

Format: `YY` + `AA` + `D` + `####` → `2608D1001`

- `YY` yılın son iki hanesi, `AA` ay (01-12)
- `D` = Ring belge kodu (Faz 2'de tır için farklı kod kullanılacak)
- `####` sayaç, **her ay 1001'den başlar**
- Aylık plan hacmi 400-500 civarı; 1001-9999 aralığı fazlasıyla yeterli
- Eş zamanlı üretim yok, ancak yine de sayaç tek transaction içinde artırılır ve
  `sefer_no` üzerinde UNIQUE kısıt vardır (yanlışlıkla iki kez çalıştırmaya karşı)
- **İptal edilen planın numarası geri kullanılmaz.** Numara akışında boşluk kalması
  normaldir ve izlenebilirlik için tercih edilir.

## 5. Plan yaşam döngüsü

```
TASLAK ──> AXATA_BEKLIYOR ──> MAIL_GONDERILDI ──> TAMAMLANDI
   │              │                   │
   └──────────────┴───────────────────┴──> IPTAL
```

- **TASLAK:** motor planı üretti, henüz onaylanmadı.
- **AXATA_BEKLIYOR:** plan onaylandı, WMS'ten Axata iş emri numarası bekleniyor.
- **MAIL_GONDERILDI:** Axata no girildi, yükleme formu depo operasyona mail atıldı.
  **Mail, Axata numarası girilmeden gönderilemez.**
- **TAMAMLANDI:** yükleme fiilen yapıldı.
- **IPTAL:** plan iptal; içindeki siparişler `BEKLEMEDE`'ye döner, sefer no yanar.

Sipariş statüleri: `BEKLEMEDE` → `PLANLANDI` → `TAMAMLANDI` (+ `HATALI`).

## 6. Açık konular (cevap bekleyenler)

| # | Konu | Durum |
|---|---|---|
| 1 | Yükleme formu Excel formatı | Bekleniyor — geldiğinde `app/services/yukleme_formu.py` doldurulacak |
| 2 | Sipariş Excel'inin gerçek kolon isimleri | Bekleniyor — `docs/veri-formatlari.md` içindeki taslak eşleme güncellenecek |
| 3 | Mail alıcı listesi ve SMTP bilgileri | Bekleniyor |
| 4 | Aynı SKU'nun farklı müşterilere giden teslimatları aynı planda birleşebilir mi? | **Varsayım: evet** (depo içi hareket olduğu için müşteri kısıtı yok) |
| 5 | Plan onayı kim tarafından veriliyor, kullanıcı/yetki yönetimi gerekli mi? | Faz 1'de tek kullanıcı varsayıldı |
