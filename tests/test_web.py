"""Web katmanı duman testi: ekranlar açılıyor ve uçtan uca akış çalışıyor mu?"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import oturum_bagimliligi
from app.main import uygulama


@pytest.fixture()
def fabrika(tmp_path):
    motor = create_engine(f"sqlite:///{tmp_path/'test.db'}", future=True)
    models.Temel.metadata.create_all(motor)
    return sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def ham_istemci(fabrika, monkeypatch):
    """Giriş yapılmamış istemci. Başlangıçta yalnızca yönetici hesabı vardır."""
    from app import main as ana

    monkeypatch.setattr(ana, "OturumFabrikasi", fabrika)
    # Gömülü master data (2.800 ürün, 5.100 müşteri) her web testinde yüklenmesin;
    # yüklendiğini tests/test_ihracat.py doğrudan doğruluyor.
    monkeypatch.setattr(ana.gomulu_veri, "eksikleri_yukle", lambda db: [])

    def oturum_ver():
        db = fabrika()
        try:
            yield db
        finally:
            db.close()

    uygulama.dependency_overrides[oturum_bagimliligi] = oturum_ver
    with TestClient(uygulama) as istemci:
        yield istemci
    uygulama.dependency_overrides.clear()


@pytest.fixture()
def istemci(ham_istemci, fabrika):
    """Yönetici olarak giriş yapmış, parolası belirlenmiş istemci."""
    from app.services import kullanici_servisi

    with fabrika() as db:
        yonetici = kullanici_servisi.kullanici_getir(db, "admin")
        yonetici.parola_ozeti = __import__(
            "app.guvenlik", fromlist=["parola_ozeti"]
        ).parola_ozeti("Yonetici2026!")
        yonetici.parola_degistirmeli = False
        db.commit()
    cevap = ham_istemci.post(
        "/giris", data={"kullanici_adi": "admin", "parola": "Yonetici2026!"}
    )
    assert cevap.status_code == 200
    return ham_istemci


def sorgu(cevap) -> str:
    """Yönlendirme sonrası URL'deki mesaj/hata parametresini okunur metne çevirir."""
    from urllib.parse import unquote_plus

    ham = cevap.url.query
    return unquote_plus(ham.decode() if isinstance(ham, bytes) else ham)


def kitap(basliklar, satirlar) -> BytesIO:
    calisma_kitabi = Workbook()
    sayfa = calisma_kitabi.active
    sayfa.append(basliklar)
    for satir in satirlar:
        sayfa.append(satir)
    tampon = BytesIO()
    calisma_kitabi.save(tampon)
    tampon.seek(0)
    return tampon


@pytest.mark.parametrize(
    "yol",
    [
        "/", "/urunler", "/ring", "/ring/siparisler", "/ring/planlar",
        "/ring/raporlar", "/ring/izleme", "/veri-yonetimi", "/yonetim/kullanicilar",
        "/rota", "/rota/siparisler", "/rota/planlar", "/rota/musteriler",
        "/rota/raporlar",
        "/raporlama", "/raporlama/siparisler", "/raporlama/planlar",
        "/ihracat", "/ihracat/siparisler", "/ihracat/planlar", "/ihracat/musteriler",
    ],
)
def test_ekranlar_acilir(istemci, yol):
    cevap = istemci.get(yol)
    assert cevap.status_code == 200
    assert "Nakliye Yönetim Sistemi" in cevap.text


@pytest.mark.parametrize(
    "yol", ["/", "/urunler", "/ring/planlar", "/yonetim/kullanicilar"]
)
def test_giris_yapmadan_erisilemez(ham_istemci, yol):
    cevap = ham_istemci.get(yol, follow_redirects=False)
    assert cevap.status_code == 303
    assert "/giris" in cevap.headers["location"]


def test_hatali_giris_reddedilir(ham_istemci):
    cevap = ham_istemci.post(
        "/giris", data={"kullanici_adi": "admin", "parola": "yanlis"}
    )
    assert "hatalı" in sorgu(cevap)


def test_ilk_giriste_parola_degistirme_zorunlu(ham_istemci, fabrika):
    from app.guvenlik import parola_ozeti
    from app.services import kullanici_servisi

    with fabrika() as db:
        yonetici = kullanici_servisi.kullanici_getir(db, "admin")
        yonetici.parola_ozeti = parola_ozeti("Gecici2026!")
        db.commit()
    ham_istemci.post("/giris", data={"kullanici_adi": "admin", "parola": "Gecici2026!"})
    cevap = ham_istemci.get("/ring/planlar", follow_redirects=False)
    assert cevap.status_code == 303
    assert cevap.headers["location"] == "/sifre-degistir"


def test_yetkisiz_kullanici_modulu_goremez(ham_istemci, fabrika):
    from app.guvenlik import parola_ozeti
    from app.models import Rol
    from app.services import kullanici_servisi

    with fabrika() as db:
        kullanici, _ = kullanici_servisi.kullanici_olustur(
            db, "depo", "Depo Görevlisi", Rol.DEPO, parola="DepoParola1!"
        )
        kullanici.parola_degistirmeli = False
        db.commit()
    ham_istemci.post("/giris", data={"kullanici_adi": "depo", "parola": "DepoParola1!"})
    assert ham_istemci.get("/ring/planlar").status_code == 403
    assert ham_istemci.get("/yonetim/kullanicilar").status_code == 403
    # Modül seçim ekranı herkese açık; yetkisi olmayan modül "yetkiniz yok" gösterir.
    assert "YETKİNİZ YOK" in ham_istemci.get("/").text


def test_goruntuleme_yetkisi_duzenlemeye_izin_vermez(ham_istemci, fabrika):
    from app.guvenlik import parola_ozeti
    from app.models import Rol
    from app.services import kullanici_servisi

    with fabrika() as db:
        kullanici, _ = kullanici_servisi.kullanici_olustur(
            db, "izleyici", "İzleyici", Rol.IZLEYICI, parola="IzleyiciP1!"
        )
        kullanici.parola_degistirmeli = False
        kullanici_servisi.yetkileri_ayarla(db, kullanici, {"RING": "GORUNTULE"})
        db.commit()
    ham_istemci.post(
        "/giris", data={"kullanici_adi": "izleyici", "parola": "IzleyiciP1!"}
    )
    assert ham_istemci.get("/ring/planlar").status_code == 200
    assert ham_istemci.post("/ring/planlar/uret", data={"depo_kodu": "64"}).status_code == 403


def test_uctan_uca_akis(istemci):
    urun_dosyasi = kitap(
        ["StokKodu", "StokAdi", "Ürün Grubu", "Palet içi adet", "Tır yükleme adeti"],
        [["KMB-24", "Kombi 24 kW", "KOMBİ", 10, 100]],
    )
    cevap = istemci.post(
        "/urunler/yukle", files={"dosya": ("urunler.xlsx", urun_dosyasi)}
    )
    assert cevap.status_code == 200 and "1 yeni" in sorgu(cevap)

    siparis_dosyasi = kitap(
        ["Sipariş No", "Teslimat No", "StokKodu", "Adet", "Depo  Kodu", "Termin Tarihi"],
        [[f"SIP-{i}", f"TSL-{i}", "KMB-24", 25, "64", "05.09.2026"] for i in range(4)],
    )
    istemci.post("/ring/siparisler/yukle", files={"dosya": ("siparis.xlsx", siparis_dosyasi)})

    cevap = istemci.post(
        "/ring/planlar/uret", data={"plan_tarihi": "2026-08-31", "depo_kodu": "64"}
    )
    assert "1 plan üretildi" in sorgu(cevap)

    planlar = istemci.get("/ring/planlar")
    assert "2608D1001" in planlar.text

    detay = istemci.get("/ring/planlar/1")
    assert detay.status_code == 200
    assert "2608D1001" in detay.text

    # Axata numarası girilmeden mail gönderilemez.
    cevap = istemci.post("/ring/planlar/1/mail")
    assert "Axata" in sorgu(cevap)

    istemci.post("/ring/planlar/1/axata", data={"axata_no": "AX-5501"})
    cevap = istemci.post("/ring/planlar/1/mail")
    assert "hata=" not in sorgu(cevap)

    form = istemci.get("/ring/planlar/1/form")
    assert form.status_code == 200
    assert form.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )

    izleme = istemci.get("/ring/izleme", params={"anahtar": "TSL-1"})
    assert "2608D1001" in izleme.text


def test_veri_silme_onay_ister(istemci):
    cevap = istemci.post("/veri-yonetimi/sil", data={"islem": "bekleyen", "onay": "evet"})
    assert "SIL yazmalısınız" in sorgu(cevap)


def test_veri_silme_onayla_calisir(istemci):
    urun_dosyasi = kitap(
        ["StokKodu", "StokAdi", "Ürün Grubu", "Palet içi adet", "Tır yükleme adeti"],
        [["KMB-24", "Kombi 24 kW", "KOMBİ", 10, 100]],
    )
    istemci.post("/urunler/yukle", files={"dosya": ("urunler.xlsx", urun_dosyasi)})
    siparis_dosyasi = kitap(
        ["Sipariş No", "Teslimat No", "StokKodu", "Adet", "Depo  Kodu", "Termin Tarihi"],
        [["SIP-1", "TSL-1", "KMB-24", 25, "64", "05.09.2026"]],
    )
    istemci.post("/ring/siparisler/yukle", files={"dosya": ("siparis.xlsx", siparis_dosyasi)})

    cevap = istemci.post(
        "/veri-yonetimi/sil", data={"islem": "bekleyen", "onay": "SIL"}
    )
    assert "1 sipariş satırı" in sorgu(cevap)
    assert "0" in istemci.get("/veri-yonetimi").text


# --------------------------------------------------- İç piyasa modülü uçtan uca


def ic_piyasa_verisi_yukle(istemci):
    """Ürün + müşteri master datası ve iki müşterili bir sipariş dosyası yükler."""
    urunler = kitap(
        ["StokKodu", "StokAdi", "Ürün Grubu", "Palet içi adet", "Tır yükleme adeti",
         "Ürün Desi"],
        [
            ["U1", "Kombi A", "KOMBİ", 10, 100, 12],
            ["U2", "Panel B", "PANEL", 10, 100, 12],
        ],
    )
    istemci.post("/urunler/yukle", files={"dosya": ("urun.xlsx", urunler)})

    musteriler = kitap(
        ["Bayi Adı", "İl", "İlçe", "Tır Girişi (E/H/?)"],
        [
            ["EGE ISITMA", "İZMİR", "BORNOVA", "E"],
            ["MANİSA TESİSAT", "MANİSA", "MERKEZ", "H"],
        ],
    )
    istemci.post("/rota/musteriler/yukle", files={"dosya": ("m.xlsx", musteriler)})

    siparisler = kitap(
        ["Sipariş No", "Teslimat No", "StokKodu", "Adet", "Depo  Kodu", "SehirAdi",
         "BayiAdi", "AliciFirma", "SevkAdresi", "Not"],
        [
            ["S1", "T1", "U1", 60, "64", "İZMİR", "EGE ISITMA", "EGE ISITMA A.Ş.",
             "1234 SOK. NO:5", "CIF - BORNOVA"],
            ["S2", "T2", "U2", 40, "74", "MANİSA", "MANİSA TESİSAT",
             "MANİSA TESİSAT LTD.", "SANAYİ CAD. NO:8", "CIF - MERKEZ"],
        ],
    )
    # İki modül aynı havuzu kullanır; iç piyasa ekranından yüklemek de aynı sonucu verir.
    return istemci.post(
        "/rota/siparisler/yukle", files={"dosya": ("siparis.xlsx", siparisler)}
    )


def test_ic_piyasa_plani_uretilir_ve_formu_indirilir(istemci, fabrika):
    from app.models import SevkiyatPlani

    ic_piyasa_verisi_yukle(istemci)

    onizleme = istemci.get("/rota/siparisler")
    assert "EGE ISITMA" in onizleme.text

    cevap = istemci.post(
        "/rota/planlar/uret", data={"tipler": ["FTL"], "plan_tarihi": "2026-09-01"}
    )
    assert "plan üretildi" in sorgu(cevap)

    with fabrika() as db:
        plan = db.query(SevkiyatPlani).filter_by(modul="ROTA").one()
        # İzmir ve Manisa aynı bölgede (Ege), tek araca binerler. Duraklar
        # Eskişehir'e uzaklığa göre sıralanır: Manisa 350 km, İzmir 400 km.
        assert plan.sevkiyat_tipi == "FTL"
        assert plan.sefer_no[4] == "S"
        assert plan.durak_sayisi == 2
        assert plan.son_ugrak == "IZMIR"
        assert plan.iller_metni == "MANISA, IZMIR"
        assert plan.ilce_metni == "MERKEZ+BORNOVA"
        # Araçtaki her il yazılır, sonuna toplam durak: "MANISA+IZMIR2YER".
        assert plan.il_yeri_metni == "MANISA+IZMIR2YER"
        # 64 hacmin çoğunu taşıyor; 74'teki mal oraya getirilecek.
        assert plan.yukleme_deposu == "64"
        plan_id = plan.id

    detay = istemci.get(f"/rota/planlar/{plan_id}")
    assert "MANİSA TESİSAT" in detay.text
    assert "64 depoya gönderilmelidir" in detay.text
    assert "Tır girişi olmayan müşteri var" in detay.text

    istemci.post(f"/rota/planlar/{plan_id}/axata", data={"axata_no": "3299, 3300"})
    istemci.post(
        f"/rota/planlar/{plan_id}/arac",
        data={"nakliyeci": "OMSAN", "plaka": "34 ABC 12", "surucu": "Ali Veli",
              "surucu_telefon": "555"},
    )

    form = istemci.get(f"/rota/planlar/{plan_id}/form")
    assert form.status_code == 200
    assert form.headers["content-type"].startswith("application/")

    gunluk = istemci.get("/rota/gunluk-form?tarih=2026-09-01")
    assert gunluk.status_code == 200


def test_ic_piyasa_formu_sevkiyat_tipine_gore_sayfalanir(istemci, fabrika, tmp_path):
    from openpyxl import load_workbook

    from app.models import SevkiyatPlani
    from app.services import ic_yukleme_formu

    ic_piyasa_verisi_yukle(istemci)
    istemci.post("/rota/planlar/uret", data={"plan_tarihi": "2026-09-01"})

    with fabrika() as db:
        planlar = db.query(SevkiyatPlani).filter_by(modul="ROTA").all()
        hedef = ic_yukleme_formu.formlari_uret(planlar, tmp_path / "form.xlsx")

    sayfa = load_workbook(hedef)["S-FTL Sevk"]
    metinler = [h.value for satir in sayfa.iter_rows() for h in satir if h.value]
    assert "Yer Miktarı" in metinler
    assert "MANISA+IZMIR2YER" in metinler
    assert "MERKEZ+BORNOVA" in metinler
    assert "Nak.Firma" in metinler
    assert "Yükleme yapacak depolar" in metinler
    assert any("depoya gönderilmelidir" in str(m) for m in metinler)
    # Kılavuz çizgileri kapalı ve form kalın çerçeve içinde.
    assert sayfa.sheet_view.showGridLines is False
    assert sayfa["A1"].border.left.style == "medium"


def test_musteri_ekranindan_tir_girisi_guncellenir(istemci, fabrika):
    from app.models import Musteri

    ic_piyasa_verisi_yukle(istemci)
    with fabrika() as db:
        musteri = db.query(Musteri).filter_by(bayi_adi="EGE ISITMA").one()
        musteri_id = musteri.id
        assert musteri.tir_girisi == "E"

    istemci.post(
        f"/rota/musteriler/{musteri_id}",
        data={"tir_girisi": "H", "bolge_kodu": "", "il": "İZMİR", "ilce": "BORNOVA",
              "notlar": "AVM içi", "aktif": "true"},
    )
    with fabrika() as db:
        musteri = db.get(Musteri, musteri_id)
        assert musteri.tir_girisi == "H"
        assert musteri.notlar == "AVM içi"
        assert musteri.il == "IZMIR"


def test_ic_piyasa_ekranindan_siparis_yuklenir(istemci, fabrika):
    """Yalnızca ROTA yetkisi olan kullanıcı Ring ekranını açamaz; yükleme burada da olmalı."""
    from app.models import SiparisSatiri

    cevap = ic_piyasa_verisi_yukle(istemci)
    assert "Sipariş aktarımı" in sorgu(cevap)

    with fabrika() as db:
        assert db.query(SiparisSatiri).count() == 2

    ekran = istemci.get("/rota/siparisler")
    assert "Sipariş dosyası yükle" in ekran.text
    assert istemci.get("/rota/siparisler/sablon").status_code == 200


def test_alinamayan_satirlar_gerekcesiyle_gosterilir(istemci, fabrika):
    """Master datada olmayan ürün planlamaya girmez; sebebi ekranda görünmeli."""
    ic_piyasa_verisi_yukle(istemci)
    tanimsiz = kitap(
        ["Sipariş No", "Teslimat No", "StokKodu", "Adet", "Depo  Kodu", "SehirAdi",
         "BayiAdi"],
        [["S9", "T9", "YOK-99", 10, "64", "İZMİR", "EGE ISITMA"]],
    )
    istemci.post("/rota/siparisler/yukle", files={"dosya": ("s.xlsx", tanimsiz)})
    istemci.post("/rota/planlar/uret", data={"plan_tarihi": "2026-09-01"})

    ekran = istemci.get("/rota/siparisler")
    assert "Alınamayan satırlar" in ekran.text
    assert "YOK-99" in ekran.text
    assert "master datada tanımlı değil" in ekran.text


def test_baslikta_marka_ve_logo_var(istemci):
    """Başlık her ekranda kurumsal kimliği taşır; logo tek dosyadan gelir."""
    cevap = istemci.get("/")
    assert "Vaillant Group" in cevap.text
    assert "Nakliye Yönetim Sistemi" in cevap.text
    assert '/static/logo.svg' in cevap.text
    assert istemci.get("/static/logo.svg").status_code == 200


def test_giris_ekraninda_da_marka_gorunur(ham_istemci):
    cevap = ham_istemci.get("/giris")
    assert "Nakliye Yönetim Sistemi" in cevap.text
    assert '/static/logo.svg' in cevap.text


def test_moduller_ayri_siparis_havuzu_kullanir(istemci, fabrika):
    """İç piyasadan yüklenen sipariş Ring ekranında görünmemeli."""
    from app.models import SiparisSatiri

    ic_piyasa_verisi_yukle(istemci)

    ring = istemci.get("/ring/siparisler")
    assert "EGE ISITMA" not in ring.text

    rota = istemci.get("/rota/siparisler")
    assert "EGE ISITMA" in rota.text

    # Raporlama ekranı hepsini bir arada gösterir.
    hepsi = istemci.get("/raporlama/siparisler")
    assert "EGE ISITMA" in hepsi.text
    assert istemci.get("/raporlama/siparisler?modul=RING").text.count("EGE ISITMA") == 0

    with fabrika() as db:
        assert {s.modul for s in db.query(SiparisSatiri).all()} == {"ROTA"}


def test_ring_planlamasi_ic_piyasa_siparisini_almaz(istemci, fabrika):
    from app.models import SevkiyatPlani

    ic_piyasa_verisi_yukle(istemci)
    cevap = istemci.post("/ring/planlar/uret", data={"depo_kodu": "64"})
    assert "Plan üretilemedi" in sorgu(cevap)

    with fabrika() as db:
        assert db.query(SevkiyatPlani).count() == 0


def test_plana_alinma_kpisi_hesaplanir(istemci, fabrika):
    """Sipariş sisteme girdikten kaç gün sonra plana alındı?"""
    ic_piyasa_verisi_yukle(istemci)
    istemci.post("/rota/planlar/uret", data={"plan_tarihi": "2026-09-01"})

    ekran = istemci.get("/raporlama")
    assert "Plana alınma süresi" in ekran.text
    assert "İç Piyasa" in ekran.text

    with fabrika() as db:
        from app.services import rapor_servisi

        kpiler = {k.modul: k for k in rapor_servisi.planlama_kpi(db)}
        kpi = kpiler["ROTA"]
        assert kpi.planlanan == 2
        # Aynı gün yüklenip aynı gün planlandı.
        assert kpi.ortalama_gun == 0
        assert kpi.ayni_gun == 2


def ihracat_verisi_yukle(istemci):
    """İhracat müşteri master datası ve iki müşterili bir sipariş dosyası yükler."""
    musteriler = kitap(
        ["Müşteri Adı", "Ülke", "Ülke Kodu", "Araç Tipi", "Sefer Kodu", "Yükleme Tipi",
         "Azami Tonaj", "Açıklama"],
        [
            ["VAILLANT D.O.O.", "HIRVATİSTAN", "HR", "TIR", "NSC", "STANDART",
             "22.000 KG", ""],
            ["ANSAL REFRIGERACION SA", "ARJANTİN", "AR", "KONTEYNER", "Export",
             "PALET YÜKSELTME", "19.500 KG", "silika jel konulacak"],
        ],
    )
    istemci.post("/ihracat/musteriler/yukle", files={"dosya": ("m.xlsx", musteriler)})

    siparisler = kitap(
        ["DEPO", "ÜLKE KODU", "SİPARİŞ NO", "ÜRÜN KODU", "ÜRÜN TANIMI", "ADET",
         "MÜŞTERİ ADI", "SEVK ADRESİ", "TESLİMAT NO", "Desi", "KG", "ÜLKE"],
        [
            ["34", "HR", "9002842146", "916041211", "Panel 600", 100,
             "VAILLANT D.O.O.", "OSIJEK", "9106800933", 20000, 15000, "HIRVATİSTAN"],
            ["34", "AR", "9002842200", "916101211", "Panel 1000", 80,
             "ANSAL REFRIGERACION SA", "BUENOS AIRES", "9106800940", 14000, 12000,
             "ARJANTİN"],
        ],
    )
    return istemci.post(
        "/ihracat/siparisler/yukle", files={"dosya": ("ihracat.xlsx", siparisler)}
    )


def test_ihracat_plani_uretilir_ve_formu_indirilir(istemci, fabrika):
    from app.models import SevkiyatPlani

    cevap = ihracat_verisi_yukle(istemci)
    assert "Sipariş aktarımı" in sorgu(cevap)

    onizleme = istemci.get("/ihracat/siparisler")
    assert "VAILLANT D.O.O." in onizleme.text
    assert "DENİZ" in onizleme.text  # Arjantin konteyner ile gider

    cevap = istemci.post("/ihracat/planlar/uret", data={"plan_tarihi": "2026-09-01"})
    assert "araç planlandı" in sorgu(cevap)

    with fabrika() as db:
        planlar = {
            p.musteri_adi: p
            for p in db.query(SevkiyatPlani).filter_by(modul="IHRACAT").all()
        }
        hirvat = planlar["VAILLANT D.O.O."]
        arjantin = planlar["ANSAL REFRIGERACION SA"]
        # Sefer belge kodu müşteriden gelir: NSC -> N, Export -> E.
        assert hirvat.sefer_no[4] == "N"
        assert arjantin.sefer_no[4] == "E"
        # Araç tipi taşıma modunu belirler.
        assert hirvat.tasima_modu == "KARA"
        assert arjantin.tasima_modu == "DENİZ"
        assert arjantin.musteri_aciklamasi == "silika jel konulacak"
        plan_id = arjantin.id

    detay = istemci.get(f"/ihracat/planlar/{plan_id}")
    assert "silika jel konulacak" in detay.text
    assert "DENİZ" in detay.text

    istemci.post(f"/ihracat/planlar/{plan_id}/axata", data={"axata_no": "2735"})
    istemci.post(
        f"/ihracat/planlar/{plan_id}/arac",
        data={"nakliyeci": "OMSAN", "plaka": "34 ABC 12",
              "konteyner_no": "MSCU1234567", "muhur_no": "M-9", "surucu": "Ali"},
    )
    assert istemci.get(f"/ihracat/planlar/{plan_id}/form").status_code == 200
    assert istemci.get("/ihracat/gunluk-form?tarih=2026-09-01").status_code == 200


def test_uc_modul_ayri_havuz_kullanir(istemci, fabrika):
    """Ring, iç piyasa ve ihracat siparişleri birbirinin ekranında görünmez."""
    from app.models import SiparisSatiri

    ic_piyasa_verisi_yukle(istemci)
    ihracat_verisi_yukle(istemci)

    assert "VAILLANT D.O.O." not in istemci.get("/rota/siparisler").text
    assert "EGE ISITMA" not in istemci.get("/ihracat/siparisler").text
    assert "EGE ISITMA" not in istemci.get("/ring/siparisler").text

    hepsi = istemci.get("/raporlama/siparisler").text
    assert "EGE ISITMA" in hepsi and "VAILLANT D.O.O." in hepsi

    with fabrika() as db:
        assert {s.modul for s in db.query(SiparisSatiri).all()} == {"ROTA", "IHRACAT"}
