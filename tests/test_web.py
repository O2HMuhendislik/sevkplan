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
    ],
)
def test_ekranlar_acilir(istemci, yol):
    cevap = istemci.get(yol)
    assert cevap.status_code == 200
    assert "SEVKİYAT PLANLAMA" in cevap.text


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
    return istemci.post(
        "/ring/siparisler/yukle", files={"dosya": ("siparis.xlsx", siparisler)}
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
        assert plan.il_yeri_metni == "MANISA2YER"
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
    assert "MANISA2YER" in metinler
    assert "MERKEZ+BORNOVA" in metinler
    assert "Nak.Firma" in metinler
    assert "Yükleme yapacak depolar" in metinler
    assert any("depoya gönderilmelidir" in str(m) for m in metinler)


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
