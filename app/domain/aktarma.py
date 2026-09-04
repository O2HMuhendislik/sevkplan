"""Parsiyel (rutin) sevkiyatın aktarma merkezleri.

Parsiyel yük müşteriye doğrudan gitmez: **Ankara, İstanbul ve Bursa** aktarma
merkezlerinden birine indirilir, dağıtımı oradan yapılır. Bu yüzden parsiyel araçta
rota kurulmaz — aracın son noktası her zaman bu üç ilden biridir.

İllerin hangi merkeze bağlandığı sahadaki tarife şu:

* **İstanbul** — Marmara, Trakya ve Batı Karadeniz.
* **Bursa** — Bursa ve batısı/güneyi: Güney Marmara, Ege, Batı Akdeniz.
* **Ankara** — Ankara ve doğusu: İç Anadolu, Karadeniz'in doğusu, Doğu ve
  Güneydoğu Anadolu, Doğu Akdeniz.

Tablo 2025'in 691 parsiyel aracındaki il birlikteliğiyle uyumlu: İstanbul en çok
Kocaeli/Sakarya/Tekirdağ/Zonguldak/Düzce/Bolu ile, Bursa Balıkesir/İzmir/Muğla/
Aydın/Çanakkale/Manisa ile, Ankara Mersin/Konya/Adana/Gaziantep/Kayseri/Samsun ile
aynı araca biniyor.

Sınırdaki iller (Bilecik, Eskişehir, Kütahya, Antalya, Kastamonu) tercihe bağlıdır;
tarife değişirse yalnızca bu dosyadaki tablo güncellenir.
"""
from __future__ import annotations

from app.domain.iller import yer_adi

ISTANBUL = "ISTANBUL"
BURSA = "BURSA"
ANKARA = "ANKARA"

AKTARMA_MERKEZLERI = (ISTANBUL, BURSA, ANKARA)

MERKEZ_ADLARI = {
    ISTANBUL: "İstanbul",
    BURSA: "Bursa",
    ANKARA: "Ankara",
}

_ISTANBUL_ILLERI = (
    "ISTANBUL", "KOCAELI", "SAKARYA", "TEKIRDAG", "EDIRNE", "KIRKLARELI",
    "YALOVA", "DUZCE", "BOLU", "ZONGULDAK", "BARTIN", "KARABUK",
)

_BURSA_ILLERI = (
    "BURSA", "BILECIK", "BALIKESIR", "CANAKKALE", "IZMIR", "MANISA", "AYDIN",
    "MUGLA", "DENIZLI", "USAK", "KUTAHYA", "AFYONKARAHISAR", "ISPARTA",
    "BURDUR", "ANTALYA",
)

IL_MERKEZLERI: dict[str, str] = {
    **{il: ISTANBUL for il in _ISTANBUL_ILLERI},
    **{il: BURSA for il in _BURSA_ILLERI},
}
"""İl -> aktarma merkezi. Listede olmayan her il Ankara'ya bağlanır."""


def aktarma_merkezi(il: str) -> str:
    """İlin bağlı olduğu aktarma merkezi.

    Tabloda olmayan il **Ankara**'ya düşer: tarifedeki "Ankara ve doğusu" kovası en
    geniş olanıdır ve İç Anadolu'dan doğuya bütün illeri kapsar.
    """
    return IL_MERKEZLERI.get(yer_adi(il), ANKARA)


def merkez_adi(kod: str) -> str:
    return MERKEZ_ADLARI.get((kod or "").upper(), kod or "")


def merkez_bolge_kodu(kod: str) -> str:
    """Plan kaydındaki bölge kodu; bölge tablosuyla karışmasın diye ön ekli."""
    return f"AKT:{(kod or '').upper()}"
