"""Parola politikası, parola saklama ve oturum yardımcıları.

Parolalar `scrypt` ile, her kullanıcıya özel rastgele tuz kullanılarak saklanır;
Python'un standart kütüphanesi dışında bir bağımlılık gerektirmez. Saklanan biçim:

    scrypt$<n>$<r>$<p>$<tuz_hex>$<ozet_hex>
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import string

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
OZET_UZUNLUGU = 32
TUZ_UZUNLUGU = 16

ASGARI_UZUNLUK = 10
OZEL_KARAKTERLER = "!@#$%^&*()-_=+[]{};:,.<>?/|~"

PAROLA_KURALLARI = (
    f"En az {ASGARI_UZUNLUK} karakter",
    "En az bir büyük harf",
    "En az bir küçük harf",
    "En az bir rakam",
    f"En az bir özel karakter ({OZEL_KARAKTERLER[:12]} …)",
)


class ParolaHatasi(ValueError):
    """Parola politikasına uymuyor."""


def parolayi_dogrula_politika(parola: str) -> None:
    """Politikaya uymayan parolada anlaşılır bir hata fırlatır."""
    eksikler: list[str] = []
    if len(parola or "") < ASGARI_UZUNLUK:
        eksikler.append(f"en az {ASGARI_UZUNLUK} karakter")
    if not re.search(r"[A-ZĞÜŞİÖÇ]", parola or ""):
        eksikler.append("en az bir büyük harf")
    if not re.search(r"[a-zğüşıöç]", parola or ""):
        eksikler.append("en az bir küçük harf")
    if not re.search(r"[0-9]", parola or ""):
        eksikler.append("en az bir rakam")
    if not any(karakter in OZEL_KARAKTERLER for karakter in parola or ""):
        eksikler.append("en az bir özel karakter")
    if eksikler:
        raise ParolaHatasi("Parola şu koşulları sağlamalı: " + ", ".join(eksikler) + ".")


def parola_ozeti(parola: str) -> str:
    tuz = os.urandom(TUZ_UZUNLUGU)
    ozet = hashlib.scrypt(
        parola.encode("utf-8"),
        salt=tuz,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=OZET_UZUNLUGU,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${tuz.hex()}${ozet.hex()}"


def parola_dogru_mu(parola: str, saklanan: str | None) -> bool:
    """Parolayı saklanan özetle karşılaştırır. Zamanlama saldırısına karşı sabit süreli."""
    if not saklanan:
        return False
    try:
        yontem, n, r, p, tuz_hex, ozet_hex = saklanan.split("$")
        if yontem != "scrypt":
            return False
        hesaplanan = hashlib.scrypt(
            (parola or "").encode("utf-8"),
            salt=bytes.fromhex(tuz_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(ozet_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(hesaplanan, bytes.fromhex(ozet_hex))


def gecici_parola_uret(uzunluk: int = 12) -> str:
    """Politikaya uyan rastgele parola üretir (yeni kullanıcı ve sıfırlama için)."""
    havuzlar = (string.ascii_uppercase, string.ascii_lowercase, string.digits, OZEL_KARAKTERLER)
    karakterler = [secrets.choice(havuz) for havuz in havuzlar]
    tum_havuz = "".join(havuzlar)
    karakterler += [secrets.choice(tum_havuz) for _ in range(max(uzunluk, ASGARI_UZUNLUK) - 4)]
    secrets.SystemRandom().shuffle(karakterler)
    return "".join(karakterler)
