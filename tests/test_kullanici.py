"""Kullanıcı, parola politikası ve yetki kuralları."""
from __future__ import annotations

import pytest

from app import guvenlik
from app.models import Rol, YetkiSeviyesi
from app.services import kullanici_servisi
from app.services.kullanici_servisi import KimlikHatasi, KullaniciHatasi


def kullanici_ekle(db, kullanici_adi="ahmet", rol=Rol.PLANLAMACI, parola="Gecici1!Abc"):
    kullanici, _ = kullanici_servisi.kullanici_olustur(
        db, kullanici_adi, "Ahmet Yılmaz", rol, parola=parola
    )
    return kullanici


# ------------------------------------------------------------------ parola politikası
@pytest.mark.parametrize(
    "parola, eksik",
    [
        ("Kisa1!", "en az 10 karakter"),
        ("hepsikucuk1!", "en az bir büyük harf"),
        ("HEPSIBUYUK1!", "en az bir küçük harf"),
        ("ParolaGecerli!", "en az bir rakam"),
        ("ParolaGecerli1", "en az bir özel karakter"),
    ],
)
def test_zayif_parolalar_reddedilir(parola, eksik):
    with pytest.raises(guvenlik.ParolaHatasi, match=eksik):
        guvenlik.parolayi_dogrula_politika(parola)


def test_gecerli_parola_kabul_edilir():
    guvenlik.parolayi_dogrula_politika("Sevkiyat2026!")


def test_uretilen_gecici_parola_politikaya_uyar():
    for _ in range(20):
        guvenlik.parolayi_dogrula_politika(guvenlik.gecici_parola_uret())


def test_parola_ozeti_geri_dondurulemez_ve_dogrulanabilir():
    ozet = guvenlik.parola_ozeti("Sevkiyat2026!")
    assert "Sevkiyat2026!" not in ozet
    assert ozet.startswith("scrypt$")
    assert guvenlik.parola_dogru_mu("Sevkiyat2026!", ozet)
    assert not guvenlik.parola_dogru_mu("Sevkiyat2026?", ozet)


def test_ayni_parola_farkli_ozet_uretir():
    """Her kullanıcıya özel tuz kullanıldığı için özetler eşleşmemeli."""
    assert guvenlik.parola_ozeti("Sevkiyat2026!") != guvenlik.parola_ozeti("Sevkiyat2026!")


# --------------------------------------------------------------------------- giriş
def test_dogru_parolayla_giris(db):
    kullanici_ekle(db)
    giren = kullanici_servisi.giris_yap(db, "ahmet", "Gecici1!Abc")
    assert giren.kullanici_adi == "ahmet"
    assert giren.son_giris is not None
    assert giren.basarisiz_deneme == 0


def test_kullanici_adi_buyuk_kucuk_harf_duyarsiz(db):
    kullanici_ekle(db)
    assert kullanici_servisi.giris_yap(db, "AHMET", "Gecici1!Abc").kullanici_adi == "ahmet"


def test_yanlis_parola_reddedilir_ve_sayaci_artirir(db):
    kullanici = kullanici_ekle(db)
    with pytest.raises(KimlikHatasi, match="hatalı"):
        kullanici_servisi.giris_yap(db, "ahmet", "YanlisParola1!")
    assert kullanici.basarisiz_deneme == 1


def test_bes_hatali_denemede_hesap_kilitlenir(db):
    kullanici = kullanici_ekle(db)
    for _ in range(kullanici_servisi.AZAMI_BASARISIZ_DENEME):
        with pytest.raises(KimlikHatasi):
            kullanici_servisi.giris_yap(db, "ahmet", "YanlisParola1!")
    assert kullanici.kilitli_mi is True
    with pytest.raises(KimlikHatasi, match="kilitlendi"):
        kullanici_servisi.giris_yap(db, "ahmet", "Gecici1!Abc")


def test_olmayan_kullanici_ayni_mesaji_verir(db):
    """Kullanıcı adının var olup olmadığı sızdırılmamalı."""
    with pytest.raises(KimlikHatasi, match="Kullanıcı adı veya parola hatalı"):
        kullanici_servisi.giris_yap(db, "yok-boyle-biri", "Herhangi1!")


def test_pasif_kullanici_giremez(db):
    kullanici = kullanici_ekle(db)
    kullanici.aktif = False
    db.flush()
    with pytest.raises(KimlikHatasi, match="pasif"):
        kullanici_servisi.giris_yap(db, "ahmet", "Gecici1!Abc")


# ------------------------------------------------------------------- parola işlemleri
def test_parola_degistirme(db):
    kullanici = kullanici_ekle(db)
    kullanici_servisi.parola_degistir(db, kullanici, "Gecici1!Abc", "YeniParola9#")
    assert kullanici.parola_degistirmeli is False
    assert kullanici_servisi.giris_yap(db, "ahmet", "YeniParola9#")


def test_yanlis_mevcut_parolayla_degistirilemez(db):
    kullanici = kullanici_ekle(db)
    with pytest.raises(KullaniciHatasi, match="Mevcut parola hatalı"):
        kullanici_servisi.parola_degistir(db, kullanici, "Yanlis1!Abc", "YeniParola9#")


def test_ayni_parolaya_degistirilemez(db):
    kullanici = kullanici_ekle(db)
    with pytest.raises(KullaniciHatasi, match="eskisiyle aynı"):
        kullanici_servisi.parola_degistir(db, kullanici, "Gecici1!Abc", "Gecici1!Abc")


def test_zayif_parolaya_degistirilemez(db):
    kullanici = kullanici_ekle(db)
    with pytest.raises(guvenlik.ParolaHatasi):
        kullanici_servisi.parola_degistir(db, kullanici, "Gecici1!Abc", "kolay")


def test_parola_sifirlama_kilidi_acar(db):
    kullanici = kullanici_ekle(db)
    kullanici.kilitli_mi = True
    kullanici.basarisiz_deneme = 5
    yeni = kullanici_servisi.parola_sifirla(db, kullanici)
    assert kullanici.kilitli_mi is False and kullanici.basarisiz_deneme == 0
    assert kullanici.parola_degistirmeli is True
    assert kullanici_servisi.giris_yap(db, "ahmet", yeni)


# ------------------------------------------------------------------------- yetkiler
def test_yonetici_her_modulu_duzenler(db):
    yonetici = kullanici_ekle(db, "admin", Rol.YONETICI)
    assert yonetici.gorebilir_mi("RING")
    assert yonetici.duzenleyebilir_mi("YONETIM")


def test_yetkisiz_kullanici_modulu_goremez(db):
    kullanici = kullanici_ekle(db)
    assert not kullanici.gorebilir_mi("RING")


def test_yetki_atama_ve_kaldirma(db):
    kullanici = kullanici_ekle(db)
    kullanici_servisi.yetkileri_ayarla(db, kullanici, {"RING": "DUZENLE", "MASTERDATA": "GORUNTULE"})
    assert kullanici.duzenleyebilir_mi("RING")
    assert kullanici.gorebilir_mi("MASTERDATA")
    assert not kullanici.duzenleyebilir_mi("MASTERDATA")

    kullanici_servisi.yetkileri_ayarla(db, kullanici, {"RING": "GORUNTULE"})
    assert kullanici.yetki_seviyesi("RING") is YetkiSeviyesi.GORUNTULE
    assert not kullanici.gorebilir_mi("MASTERDATA")


def test_tanimsiz_modul_yetkisi_reddedilir(db):
    kullanici = kullanici_ekle(db)
    with pytest.raises(KullaniciHatasi, match="Tanımsız modül"):
        kullanici_servisi.yetkileri_ayarla(db, kullanici, {"OLMAYAN": "DUZENLE"})


def test_mukerrer_kullanici_adi_reddedilir(db):
    kullanici_ekle(db)
    with pytest.raises(KullaniciHatasi, match="zaten kayıtlı"):
        kullanici_ekle(db)


def test_ilk_kurulumda_yonetici_olusur(db):
    parola = kullanici_servisi.varsayilan_yoneticiyi_olustur(db)
    assert parola is not None
    yonetici = kullanici_servisi.kullanici_getir(db, "admin")
    assert yonetici.rol is Rol.YONETICI and yonetici.parola_degistirmeli
    # İkinci çağrı yeni kullanıcı açmaz.
    assert kullanici_servisi.varsayilan_yoneticiyi_olustur(db) is None
