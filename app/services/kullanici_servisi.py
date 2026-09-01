"""Kullanıcı yönetimi: kimlik doğrulama, parola işlemleri, modül yetkileri."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import guvenlik
from app.models import Kullanici, ModulYetkisi, Rol, YetkiSeviyesi
from app.moduller import MODUL_HARITASI

AZAMI_BASARISIZ_DENEME = 5
VARSAYILAN_YONETICI = "admin"


class KimlikHatasi(Exception):
    """Giriş başarısız; mesaj doğrudan kullanıcıya gösterilir."""


class KullaniciHatasi(Exception):
    """Kullanıcı işleminde iş kuralı ihlali."""


def kullanici_getir(db: Session, kullanici_adi: str) -> Kullanici | None:
    return db.scalar(
        select(Kullanici).where(
            func.lower(Kullanici.kullanici_adi) == (kullanici_adi or "").strip().lower()
        )
    )


def giris_yap(db: Session, kullanici_adi: str, parola: str) -> Kullanici:
    """Kullanıcıyı doğrular. Hatalı denemeler sayılır, sınır aşılınca hesap kilitlenir."""
    kullanici = kullanici_getir(db, kullanici_adi)
    if kullanici is None or not guvenlik.parola_dogru_mu(parola, kullanici.parola_ozeti):
        if kullanici is not None:
            kullanici.basarisiz_deneme += 1
            if kullanici.basarisiz_deneme >= AZAMI_BASARISIZ_DENEME:
                kullanici.kilitli_mi = True
            db.flush()
        # Kullanıcı adının var olup olmadığını sızdırmamak için tek mesaj.
        raise KimlikHatasi("Kullanıcı adı veya parola hatalı.")

    if not kullanici.aktif:
        raise KimlikHatasi("Bu hesap pasif durumda. Yöneticinize başvurun.")
    if kullanici.kilitli_mi:
        raise KimlikHatasi(
            "Hesap çok sayıda hatalı denemeden dolayı kilitlendi. "
            "Yöneticinizin kilidi açması gerekiyor."
        )

    kullanici.basarisiz_deneme = 0
    kullanici.son_giris = datetime.now()
    db.flush()
    return kullanici


def kullanici_olustur(
    db: Session,
    kullanici_adi: str,
    ad_soyad: str,
    rol: Rol,
    eposta: str | None = None,
    firma: str | None = None,
    parola: str | None = None,
) -> tuple[Kullanici, str]:
    """Kullanıcı oluşturur, (kullanıcı, ilk parola) döner.

    Parola verilmezse politikaya uyan geçici bir parola üretilir; kullanıcı ilk
    girişinde değiştirmek zorundadır.
    """
    kullanici_adi = (kullanici_adi or "").strip()
    if not kullanici_adi:
        raise KullaniciHatasi("Kullanıcı adı boş olamaz.")
    if not (ad_soyad or "").strip():
        raise KullaniciHatasi("Ad soyad boş olamaz.")
    if kullanici_getir(db, kullanici_adi) is not None:
        raise KullaniciHatasi(f"{kullanici_adi} kullanıcı adı zaten kayıtlı.")

    ilk_parola = parola or guvenlik.gecici_parola_uret()
    guvenlik.parolayi_dogrula_politika(ilk_parola)

    kullanici = Kullanici(
        kullanici_adi=kullanici_adi,
        ad_soyad=ad_soyad.strip(),
        eposta=(eposta or "").strip() or None,
        firma=(firma or "").strip() or None,
        rol=rol,
        parola_ozeti=guvenlik.parola_ozeti(ilk_parola),
        parola_degistirmeli=True,
    )
    db.add(kullanici)
    db.flush()
    return kullanici, ilk_parola


def parola_degistir(
    db: Session, kullanici: Kullanici, mevcut_parola: str, yeni_parola: str
) -> None:
    if not guvenlik.parola_dogru_mu(mevcut_parola, kullanici.parola_ozeti):
        raise KullaniciHatasi("Mevcut parola hatalı.")
    if guvenlik.parola_dogru_mu(yeni_parola, kullanici.parola_ozeti):
        raise KullaniciHatasi("Yeni parola eskisiyle aynı olamaz.")
    guvenlik.parolayi_dogrula_politika(yeni_parola)
    kullanici.parola_ozeti = guvenlik.parola_ozeti(yeni_parola)
    kullanici.parola_degistirmeli = False
    db.flush()


def parola_sifirla(db: Session, kullanici: Kullanici) -> str:
    """Yönetici işlemi: geçici parola üretir, kilidi açar."""
    yeni = guvenlik.gecici_parola_uret()
    kullanici.parola_ozeti = guvenlik.parola_ozeti(yeni)
    kullanici.parola_degistirmeli = True
    kullanici.kilitli_mi = False
    kullanici.basarisiz_deneme = 0
    db.flush()
    return yeni


def yetkileri_ayarla(db: Session, kullanici: Kullanici, secimler: dict[str, str]) -> None:
    """Kullanıcının modül yetkilerini verilen sözlükle değiştirir.

    `secimler`: {modul_kodu: "GORUNTULE" | "DUZENLE"}. Listede olmayan modüllerin
    yetkisi kaldırılır.
    """
    gecersiz = set(secimler) - set(MODUL_HARITASI)
    if gecersiz:
        raise KullaniciHatasi(f"Tanımsız modül: {', '.join(sorted(gecersiz))}")

    mevcut = {yetki.modul_kodu: yetki for yetki in kullanici.yetkiler}
    for modul_kodu, seviye in secimler.items():
        hedef = YetkiSeviyesi(seviye)
        if modul_kodu in mevcut:
            mevcut[modul_kodu].seviye = hedef
        else:
            kullanici.yetkiler.append(
                ModulYetkisi(modul_kodu=modul_kodu, seviye=hedef)
            )
    for modul_kodu, yetki in mevcut.items():
        if modul_kodu not in secimler:
            kullanici.yetkiler.remove(yetki)
    db.flush()


def kullanicilari_getir(db: Session) -> list[Kullanici]:
    return list(
        db.scalars(select(Kullanici).order_by(Kullanici.aktif.desc(), Kullanici.ad_soyad)).all()
    )


def yonetici_sayisi(db: Session) -> int:
    return db.scalar(
        select(func.count(Kullanici.id)).where(
            Kullanici.rol == Rol.YONETICI, Kullanici.aktif.is_(True)
        )
    ) or 0


def varsayilan_yoneticiyi_olustur(db: Session) -> str | None:
    """Sistemde hiç kullanıcı yoksa bir yönetici hesabı açar ve parolasını döner.

    Parola yalnızca bu anda görünür; kullanıcı ilk girişinde değiştirmek zorundadır.
    """
    if db.scalar(select(func.count(Kullanici.id))):
        return None
    _, parola = kullanici_olustur(
        db,
        kullanici_adi=VARSAYILAN_YONETICI,
        ad_soyad="Sistem Yöneticisi",
        rol=Rol.YONETICI,
    )
    return parola
