# Sunucu Kurulumu ve Ortak Kullanım

Bu doküman, programın ekip tarafından ortak kullanılacak şekilde yayına alınması için
gerekenleri anlatır. IT ekibiyle paylaşılabilir.

---

## Kısa cevaplar

**SharePoint'te veri tutabilir miyiz?** Hayır. SharePoint bir doküman kütüphanesidir,
veritabanı sunucusu değil. Veritabanı dosyası SharePoint / OneDrive senkronize bir
klasörde tutulursa **veri bozulur**: iki kişi aynı anda yazdığında dosya kilitleme
ağ paylaşımı üzerinde güvenilir çalışmaz, senkronizasyon dosyayı kopyalar ve
"çakışan kopya" üretir. Aynı kısıt ağ sürücüsü (`\\sunucu\paylasim`) için de geçerlidir.

SharePoint yine de kullanılabilir ama **veri için değil**: yükleme formlarının ve
raporların arşivlendiği yer olarak uygundur. Program çıktıyı oraya yazabilir.

**Ekibin bilgisayarına kurmak gerekiyor mu?** Hayır. Program zaten web tabanlı.
Tek bir sunucuya kurulur, herkes tarayıcıdan `https://sevkplan.sirket.com` gibi bir
adrese girer. Kullanıcı bilgisayarına hiçbir şey kurulmaz.

**Şu an neden sadece kendi bilgisayarımda çalışıyor?** Program yalnızca `127.0.0.1`
adresini dinliyor. Ağa açmak için `--host 0.0.0.0` ile başlatmak yeterli — ama kalıcı
kurulum için aşağıdaki adımlar gerekir.

---

## Ne gerekiyor — IT'den istenecekler listesi

| # | İhtiyaç | Açıklama |
|---|---|---|
| 1 | **Sunucu** | Windows Server veya Linux sanal makine. 2 vCPU / 4 GB RAM / 50 GB disk yeterli. |
| 2 | **Veritabanı** | PostgreSQL 14+ (tercih) veya SQL Server. Aynı sunucuda olabilir. |
| 3 | **DNS adı** | `sevkplan.sirket.com.tr` gibi bir iç ad. |
| 4 | **HTTPS sertifikası** | İç sertifika otoritesi ya da Let's Encrypt. Parolalar şifresiz ağdan geçmemeli. |
| 5 | **Yedekleme** | Veritabanının günlük yedeği. |
| 6 | **Dış erişim kararı** | Sözleşmeli nakliyeci erişecekse: VPN mi, internete açık mı? (aşağıya bakın) |
| 7 | **SMTP bilgisi** | Yükleme formunun otomatik mail atması için sunucu adresi, port, gönderen hesap. |

---

## Seçenek A — Şirket içi sunucu (önerilen başlangıç)

Kurumsal ağda bir Windows Server ya da Linux VM.

**Artıları:** veri şirket içinde kalır, mevcut yedekleme ve güvenlik politikalarına dahil
olur, ek abonelik maliyeti yok.
**Eksileri:** dışarıdan (nakliyeci) erişim için ayrıca çözüm gerekir.

### Windows Server'da kurulum

```powershell
# 1. Python 3.11+ kurun (kurulumda "Add Python to PATH" işaretli)
# 2. Programı C:\sevkplan altına çıkarın
cd C:\sevkplan
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install "psycopg[binary]==3.2.3"   # PostgreSQL kullanılacaksa

# 3. Ayarları ortam değişkeni olarak verin (Sistem Özellikleri > Ortam Değişkenleri)
#    SEVKPLAN_DB_URL          = postgresql+psycopg://sevkplan:PAROLA@dbsunucu:5432/sevkplan
#    SEVKPLAN_OTURUM_ANAHTARI = (64 karakterlik rastgele metin, aşağıdaki komutla üretin)
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"

# 4. Deneme amaçlı çalıştırın
.venv\Scripts\python -m uvicorn app.main:uygulama --host 0.0.0.0 --port 8000
```

Tarayıcıdan `http://sunucu-adi:8000` ile ulaşılabildiğini doğrulayın, sonra kalıcı hale
getirin.

### Windows servisi olarak çalıştırma

Komut İstemi penceresi kapanınca program durmasın diye Windows servisi yapılır. En
pratik yol [NSSM](https://nssm.cc):

```powershell
nssm install SevkiyatPlanlama "C:\sevkplan\.venv\Scripts\python.exe" ^
  "-m uvicorn app.main:uygulama --host 0.0.0.0 --port 8000 --workers 2"
nssm set SevkiyatPlanlama AppDirectory C:\sevkplan
nssm set SevkiyatPlanlama Start SERVICE_AUTO_START
nssm start SevkiyatPlanlama
```

### Linux'ta systemd servisi

```ini
# /etc/systemd/system/sevkplan.service
[Unit]
Description=Sevkiyat Planlama
After=network.target postgresql.service

[Service]
User=sevkplan
WorkingDirectory=/opt/sevkplan
Environment="SEVKPLAN_DB_URL=postgresql+psycopg://sevkplan:PAROLA@localhost:5432/sevkplan"
Environment="SEVKPLAN_OTURUM_ANAHTARI=..."
ExecStart=/opt/sevkplan/.venv/bin/uvicorn app.main:uygulama --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now sevkplan
```

### HTTPS ve DNS

Uygulamayı doğrudan 443'e açmayın; önüne bir ters vekil sunucu koyun.

* **Linux:** Nginx veya Caddy. Caddy sertifikayı kendi alır:
  ```
  sevkplan.sirket.com.tr {
      reverse_proxy 127.0.0.1:8000
  }
  ```
* **Windows:** IIS + Application Request Routing, ya da Caddy'nin Windows sürümü.

---

## Seçenek B — Azure (Microsoft 365 kullandığınız için doğal seçenek)

Şirket zaten Microsoft 365 kullandığı için Azure aboneliği genelde vardır.

* **Azure App Service (Linux, Python 3.11)** — sunucu yönetimi yok, HTTPS ve alan adı
  hazır geliyor, ölçekleme tek düğme. Uygulama doğrudan çalışır.
* **Azure Database for PostgreSQL (Flexible Server)** — yönetilen veritabanı, otomatik
  yedek.
* Dış kullanıcı erişimi App Service üzerinden doğal olarak çözülür; ayrıca
  **Microsoft Entra ID (Azure AD)** ile şirket hesabıyla tek tıkla giriş eklenebilir.

**Artıları:** kurulum ve bakım yükü düşük, dış erişim kolay, yedekleme dahil.
**Eksileri:** aylık abonelik maliyeti, veri bulutta (şirket politikası uygun olmalı).

Tahmini büyüklük: B1 App Service + B1ms PostgreSQL bu iş yükü için fazlasıyla yeter.

---

## Nakliyeci erişimi (Araç Talep ve Tedarik modülü)

Sözleşmeli nakliyeci şirket ağında olmadığı için üç yol var:

1. **VPN** — nakliyeciye VPN hesabı verilir, iç sunucuya erişir. En güvenlisi, ama
   nakliyeci tarafında kurulum ve destek yükü doğurur.
2. **İnternete açık sunucu (DMZ / Azure)** — nakliyeci doğrudan tarayıcıdan girer.
   Bu durumda mutlaka: HTTPS, güçlü parola politikası (sistemde var), hesap kilitleme
   (sistemde var), IP kısıtı (mümkünse), düzenli güncelleme.
3. **Karma** — iç kullanıcılar VPN'siz iç ağdan, nakliyeci internete açık ayrı bir
   adresten. Aynı uygulama, farklı ağ yolu.

Sistem tarafında hazırlık yapıldı: nakliyeci `NAKLIYECI` rolüyle açılır ve yalnızca
kendisine yetki verilen modülü görür; diğer ekranlara URL'yi bilse bile erişemez.

---

## Veritabanı seçimi

| Kullanım | Veritabanı |
|---|---|
| Tek kişi, deneme | SQLite (varsayılan, kurulum gerektirmez) |
| **Ekip kullanımı** | **PostgreSQL** |

SQLite tek bir dosyadır ve aynı anda birden fazla kişi yazdığında kilitlenmeler yaşanır;
ağ paylaşımında ise veri bozulur. Ekip kullanımına geçerken PostgreSQL'e taşınmalıdır.

Geçiş için kodda değişiklik gerekmez, tek yapılacak `SEVKPLAN_DB_URL` ortam
değişkenini vermektir:

```
SEVKPLAN_DB_URL=postgresql+psycopg://sevkplan:PAROLA@dbsunucu:5432/sevkplan
```

Program ilk açılışta tabloları kendisi oluşturur. Mevcut SQLite verisini taşımak
gerekirse ürün ve sipariş Excel'lerini yeni sisteme yeniden yüklemek en pratik yoldur.

---

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `SEVKPLAN_DB_URL` | `sqlite:///veri/sevkplan.db` | Veritabanı bağlantısı |
| `SEVKPLAN_OTURUM_ANAHTARI` | veri klasöründe üretilir | Oturum çerezlerini imzalar. **Sunucuda mutlaka verin**; birden fazla iş parçacığı çalıştığında ortak olmalı. |
| `SEVKPLAN_OTURUM_SURESI` | `480` | Hareketsiz oturumun kapanma süresi (dakika) |
| `SEVKPLAN_VERI_DIZIN` | `veri` | Çıktı ve yükleme klasörü |
| `SEVKPLAN_ESNETME_ASGARI_ORAN` | `0` | Alt limit esnetildiğinde açılmayacak asgari doluluk |
| `SEVKPLAN_GRUP_ICI_MIX` | `1` | Grup içi karışık planlamanın varsayılanı |

---

## Yedekleme

* **PostgreSQL:** günlük `pg_dump`, en az 30 gün saklama.
* **SQLite:** `veri/sevkplan.db` dosyasının program kapalıyken kopyalanması.
* Yükleme formu çıktıları `veri/ciktilar` altındadır; SharePoint'e senkronlanabilir.

---

## İlk giriş

Program ilk çalıştırıldığında konsola bir yönetici hesabı ve **geçici parola** yazar:

```
İLK KURULUM — yönetici hesabı oluşturuldu
  Kullanıcı adı : admin
  Geçici parola : ...
```

Bu parola bir daha gösterilmez. İlk girişte değiştirilmesi zorunludur. Sonrasında
**Sistem Yönetimi > Kullanıcılar** ekranından diğer kullanıcılar açılır.

Servis olarak çalıştırıyorsanız bu satır servis günlüğüne yazılır (NSSM'de
`AppStdout`, systemd'de `journalctl -u sevkplan`).

---

## İleride: şirket hesabıyla giriş (SSO)

Microsoft 365 kullandığınız için iç kullanıcılar kendi şirket hesaplarıyla
(Entra ID / Azure AD) girebilir; ayrı parola hatırlamalarına gerek kalmaz. Nakliyeciler
şirket hesabına sahip olmadığı için onlar sistemdeki kullanıcı adı/parola ile devam eder.
Karma yapı desteklenebilir; mevcut kullanıcı altyapısı buna uygun kuruldu.
