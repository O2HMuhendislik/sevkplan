# Kurulum ve Çalıştırma Kılavuzu

Bu kılavuz, programı kendi bilgisayarında (Windows) çalıştırman için yazıldı.
Yazılım bilgisi gerektirmez. Sırayla takip et.

---

## Adım 1 — Dosyaları bilgisayarına al

Sana gönderilen `sevkplan.zip` dosyasını indir. Üzerine sağ tıkla →
**Tümünü ayıkla** (Extract All) → örneğin `C:\sevkplan` klasörüne çıkar.

İşin bitince `C:\sevkplan` klasörünün içinde `app`, `docs`, `tests` gibi
klasörler ve `README.md`, `requirements.txt` gibi dosyalar görüyor olmalısın.

---

## Adım 2 — Python kurulu mu, kontrol et

1. Başlat menüsüne `cmd` yazıp **Komut İstemi**'ni aç.
2. Şunu yazıp Enter'a bas:

   ```
   python --version
   ```

3. `Python 3.11.5` gibi bir yazı çıkarsa Python kurulu, Adım 3'e geç.

   Hata alırsan veya Microsoft Store açılırsa: <https://www.python.org/downloads/>
   adresinden Python'u indir. Kurulum ekranındaki **"Add Python to PATH"**
   kutusunu işaretlemeyi unutma — en sık yapılan hata budur. Kurduktan sonra
   Komut İstemi'ni kapatıp yeniden aç ve komutu tekrar dene.

---

## Adım 3 — Programın klasörüne git

Komut İsteminde:

```
cd C:\sevkplan
```

(Dosyaları başka bir yere çıkardıysan o yolu yaz.)

---

## Adım 4 — Gerekli paketleri kur (yalnızca ilk seferde)

Sırayla üç komut. Her birinden sonra Enter'a bas ve bitmesini bekle.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

* İlk komut, programın kendine ait bir çalışma alanı oluşturur
  (bilgisayarındaki diğer Python kurulumlarına karışmaz).
* İkinci komut o alanı devreye alır. Başarılı olduğunda satırın başında
  `(.venv)` yazısını görürsün.
* Üçüncü komut programın ihtiyaç duyduğu bileşenleri internetten indirir.
  Bir-iki dakika sürebilir.

---

## Adım 5 — Programı başlat

```
uvicorn app.main:uygulama --reload
```

Ekranda şuna benzer bir satır görürsün:

```
Uvicorn running on http://127.0.0.1:8000
```

Tarayıcını aç ve adres çubuğuna şunu yaz:

**http://127.0.0.1:8000**

Program açılacak.

> **Önemli:** Program çalışırken Komut İstemi penceresi açık kalmalı.
> Kapatırsan program durur. Durdurmak için o pencerede `Ctrl + C`.

---

## Adım 6 (isteğe bağlı) — Örnek veriyle dene

Boş bir ekran yerine dolu bir sistem görmek istersen, programı başlatmadan
önce şunu çalıştır:

```
python -m scripts.ornek_veri
```

8 ürün ve 60 sipariş satırı oluşturup planlamayı çalıştırır. Sonra Adım 5'e
dönüp programı başlat; planları hazır göreceksin.

Bu veriyi silip sıfırdan başlamak istersen `veri` klasöründeki
`sevkplan.db` dosyasını sil. Program bir sonraki açılışta yenisini oluşturur.

---

## Sonraki açılışlarda

İlk kurulumu bir kez yaparsın. Sonraki günlerde sadece şu üç satır:

```
cd C:\sevkplan
.venv\Scripts\activate
uvicorn app.main:uygulama --reload
```

---

## Sık karşılaşılan sorunlar

| Hata | Anlamı ve çözümü |
|---|---|
| `'python' is not recognized...` | Python kurulu değil ya da PATH'e eklenmemiş. Adım 2'yi tekrarla, kurulumda "Add Python to PATH" kutusunu işaretle. |
| `'uvicorn' is not recognized...` | `.venv\Scripts\activate` komutunu çalıştırmayı atlamışsın. Satır başında `(.venv)` yazdığından emin ol. |
| `.venv\Scripts\activate` çalışmıyor, izin hatası veriyor | PowerShell yerine **Komut İstemi (cmd)** kullan. |
| `Address already in use` / port meşgul | Program zaten başka bir pencerede açık. O pencereyi bul ve `Ctrl + C` ile kapat, ya da farklı port kullan: `uvicorn app.main:uygulama --port 8001` (tarayıcıda `http://127.0.0.1:8001`). |
| Tarayıcıda sayfa açılmıyor | Komut İstemi penceresinde `Uvicorn running` yazısı duruyor mu, kontrol et. Adresi elle yaz: `http://127.0.0.1:8000` |

---

## Programı ilk açtığında ne yapmalısın

1. **Master Data** ekranına git, ürünlerini tanımla. En önemli alan
   **Palet İçi Adet** — planlamanın tek sayısal girdisi budur.
   Tek tek girebilir ya da "Şablonu indir" ile aldığın Excel'i doldurup
   toplu yükleyebilirsin.
2. **Siparişler** ekranından sipariş Excel'ini yükle.
3. **Planlar** ekranında "Planlamayı çalıştır" de.
4. Üretilen planın detayına gir, **Axata numarasını** yaz, yükleme formunu indir.
