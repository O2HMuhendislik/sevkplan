"""Yönetici hesabı ve parola işlemleri (komut satırı).

Parolanızı unuttuğunuzda ya da ilk kurulumda ekrana yazılan geçici parolayı
kaçırdığınızda kullanılır. Program kapalıyken çalıştırın.

Kullanım:
    python -m scripts.yonetici                    # admin parolasını sıfırlar
    python -m scripts.yonetici ahmet              # ahmet'in parolasını sıfırlar
    python -m scripts.yonetici --liste            # kullanıcıları listeler
    python -m scripts.yonetici --parola "Sevkiyat2026!"   # parolayı kendiniz belirler
"""
from __future__ import annotations

import argparse

from app.db import oturum, semayi_olustur
from app.guvenlik import ParolaHatasi, parola_ozeti, parolayi_dogrula_politika
from app.models import Rol
from app.services import kullanici_servisi


def listele() -> None:
    with oturum() as db:
        kullanicilar = kullanici_servisi.kullanicilari_getir(db)
        if not kullanicilar:
            print("Kayıtlı kullanıcı yok.")
            return
        print(f"{'Kullanıcı adı':<20}{'Ad Soyad':<28}{'Rol':<14}{'Durum'}")
        print("-" * 76)
        for k in kullanicilar:
            durum = "aktif" if k.aktif else "pasif"
            if k.kilitli_mi:
                durum += ", KİLİTLİ"
            if k.parola_degistirmeli:
                durum += ", parola değiştirecek"
            print(f"{k.kullanici_adi:<20}{k.ad_soyad:<28}{k.rol.value:<14}{durum}")


def sifirla(kullanici_adi: str, parola: str | None) -> None:
    with oturum() as db:
        kullanici = kullanici_servisi.kullanici_getir(db, kullanici_adi)

        if kullanici is None:
            if kullanici_adi != kullanici_servisi.VARSAYILAN_YONETICI:
                print(f"'{kullanici_adi}' adlı kullanıcı bulunamadı.")
                print("Kayıtlı kullanıcılar için: python -m scripts.yonetici --liste")
                raise SystemExit(1)
            # admin hiç yoksa oluştur
            kullanici, uretilen = kullanici_servisi.kullanici_olustur(
                db,
                kullanici_adi=kullanici_servisi.VARSAYILAN_YONETICI,
                ad_soyad="Sistem Yöneticisi",
                rol=Rol.YONETICI,
                parola=parola,
            )
            yeni_parola = parola or uretilen
            print("Yönetici hesabı bulunamadı, yeniden oluşturuldu.")
        elif parola:
            parolayi_dogrula_politika(parola)
            kullanici.parola_ozeti = parola_ozeti(parola)
            kullanici.parola_degistirmeli = False
            kullanici.kilitli_mi = False
            kullanici.basarisiz_deneme = 0
            yeni_parola = parola
        else:
            yeni_parola = kullanici_servisi.parola_sifirla(db, kullanici)

        if kullanici.rol is not Rol.YONETICI and kullanici_servisi.yonetici_sayisi(db) == 0:
            kullanici.rol = Rol.YONETICI
            print("Sistemde aktif yönetici kalmadığı için bu hesap yönetici yapıldı.")

        print()
        print("=" * 60)
        print(f"  Kullanıcı adı : {kullanici.kullanici_adi}")
        print(f"  Yeni parola   : {yeni_parola}")
        if kullanici.parola_degistirmeli:
            print("  İlk girişte parolanızı değiştirmeniz istenecek.")
        print("=" * 60)
        print()


def main() -> None:
    ayrıştırıcı = argparse.ArgumentParser(
        description="Yönetici hesabı ve parola işlemleri",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ayrıştırıcı.add_argument(
        "kullanici_adi",
        nargs="?",
        default=kullanici_servisi.VARSAYILAN_YONETICI,
        help="Parolası sıfırlanacak kullanıcı (varsayılan: admin)",
    )
    ayrıştırıcı.add_argument("--liste", action="store_true", help="Kullanıcıları listeler")
    ayrıştırıcı.add_argument(
        "--parola", help="Rastgele üretmek yerine bu parolayı ayarlar"
    )
    argümanlar = ayrıştırıcı.parse_args()

    semayi_olustur()
    if argümanlar.liste:
        listele()
        return
    try:
        sifirla(argümanlar.kullanici_adi, argümanlar.parola)
    except ParolaHatasi as hata:
        print(f"Parola kabul edilmedi: {hata}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
