"""Omsan fiyat listelerini programın tarife dosyasına çevirir.

Kullanım:
    python -m scripts.nakliye_tarifesi_aktar <FTL_dosyasi.xlsx> <parsiyel_dosyasi.xlsx>
                                             [--gecerlilik YYYY-AA-GG]

`--gecerlilik` verilmezse tarih listenin kendi başlığından okunur. Liste yılın
ortasında revize edilmiş olabilir; geçmiş sevkleri o listeyle değerlemek için
başlangıç tarihi geriye çekilir (ör. `--gecerlilik 2026-01-01`).

Üretilen dosya: `veri/ornek/nakliye_tarifesi.xlsx` — üç sayfa (Tarifeler,
Ek Ücretler, Açıklama). Boş bir veritabanı ilk açılışta bunu yükler; ekrandan
da yüklenebilir.

**Kaynak dosyaların yapısı**

* FTL (`2026 FTL` sayfası) — 1. satırda motorin fiyatı, 2. satırda tarife tarihi,
  3. satırda başlıklar. Sütunlar: Operasyon, Yükleme Noktası, Varış Noktası,
  Bölge, Kamyon (TL/Sefer), Tır (TL/Sefer). Yalnızca **Outbound FTL Eskişehir**
  ve **Outbound FTL Bozüyük** satırları alınır; Inbound ve Arçelik satırları
  bizim sevkiyatımız değil. Ayrıca `Uğrama (2nk)` ve `Ek Km` satırları ek ücret
  olarak yazılır.
* Parsiyel — 1. satırda asgari gönderi bedeli, 3. satırda başlıklar. Üç desi
  kademesi var (0-2000, 2001-4000, 4001+). Yalnızca yükleme noktası Eskişehir
  ya da Bozüyük olan satırlar alınır; gerisi inbound.

**İl adı eşlemesi.** Listede varış noktası bazen ilçe ya da bölge adı:
`And.İstanbul`, `İstanbul Avcılar`, `Gebze` gibi. Bunlar ile + ilçe olarak
ayrıştırılır; program önce ilçe satırını arar, bulamazsa ilin genel satırına
düşer. İstanbul'un genel satırı için **en yüksek** varyant kullanılır: hangi
yakaya gittiği bilinmeyen bir aracı düşük fiyatlamak, maliyet kontrolünde
yüksek fiyatlamaktan daha yanıltıcıdır. Satır ekrandan düzenlenebilir.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from app.domain.iller import yer_adi
from app.services.excel import sayfa_yaz, yeni_kitap
from app.services.veri_formatlari import EK_UCRET_ALANLARI, TARIFE_ALANLARI

HEDEF = Path("veri/ornek/nakliye_tarifesi.xlsx")

CIKIS_NOKTALARI = {"ESKISEHIR": "ESKİŞEHİR", "BOZUYUK": "BOZÜYÜK"}
"""Kaynak dosyadaki yükleme noktası -> `Depo.tesis` değeri."""

OUTBOUND_OPERASYONLARI = {"Outbound FTL Eskişehir", "Outbound FTL Bozüyük"}

# Varış noktası -> (il, ilçe). İlçesi olmayanlar doğrudan `yer_adi` ile çözülür.
VARIS_ESLEMESI: dict[str, tuple[str, str | None]] = {
    "AND.ISTANBUL": ("ISTANBUL", "ANADOLU"),
    "ISTANBUL ANADOLU": ("ISTANBUL", "ANADOLU"),
    "AVR.ISTANBUL": ("ISTANBUL", "AVRUPA"),
    "ISTANBUL AVRUPA": ("ISTANBUL", "AVRUPA"),
    "ISTANBUL AVCILAR": ("ISTANBUL", "AVCILAR"),
    "ISTANBUL SILIVRI": ("ISTANBUL", "SILIVRI"),
    "GEBZE": ("KOCAELI", "GEBZE"),
    # Parsiyel listesinde Eskişehir çıkışlı İstanbul tek satır ve ortalama fiyat;
    # ilçe kırılımı yok, ilin geneli olarak alınır.
    "ISTANBUL ORT.": ("ISTANBUL", None),
    "ISTANBUL ORT": ("ISTANBUL", None),
}


def _varisi_coz(deger) -> tuple[str, str | None] | None:
    ad = yer_adi(deger)
    if not ad or ad in {"EK KM", "UGRAMA (2NK)"}:
        return None
    if ad in VARIS_ESLEMESI:
        return VARIS_ESLEMESI[ad]
    if "DEPOLAR ARASI" in ad:
        return None
    return (ad, None)


def _ondalik(deger) -> Decimal | None:
    if deger in (None, ""):
        return None
    return Decimal(str(deger)).quantize(Decimal("0.0001"))


def ftl_oku(dosya: Path) -> tuple[list[dict], list[dict], Decimal | None, date]:
    sayfa = load_workbook(dosya, read_only=True, data_only=True)["2026 FTL"]
    satirlar = list(sayfa.iter_rows(values_only=True))

    motorin = None
    for hucre in satirlar[0]:
        if hucre and "Motorin" in str(hucre):
            motorin = Decimal(str(hucre).split(":")[1].strip().replace(",", "."))
    tarih = next(
        (h.date() for h in satirlar[1] if isinstance(h, datetime)), date.today()
    )

    tarifeler: list[dict] = []
    ek_ucretler: list[dict] = []
    for satir in satirlar[3:]:
        operasyon, yukleme, varis, _bolge = satir[0], satir[1], satir[2], satir[3]
        kamyon, tir = _ondalik(satir[4]), _ondalik(satir[5])

        if yer_adi(varis) == "UGRAMA (2NK)":
            for arac, tutar in (("KAMYON", kamyon), ("TIR", tir)):
                ek_ucretler.append({
                    "tur": "UGRAMA", "sevkiyat_tipi": "FTL", "arac_tipi": arac,
                    "cikis_noktasi": "", "tutar": tutar, "esik": 2,
                    "gecerlilik_baslangic": tarih, "gecerlilik_bitis": None,
                    "nakliyeci": "OMSAN", "motorin_fiyati": motorin,
                    "aciklama": "İlk iki uğrama sefer fiyatına dahil; sonrakiler ödenir.",
                })
            continue
        if yer_adi(varis) == "EK KM":
            for arac, tutar in (("KAMYON", kamyon), ("TIR", tir)):
                ek_ucretler.append({
                    "tur": "EK_KM", "sevkiyat_tipi": "FTL", "arac_tipi": arac,
                    "cikis_noktasi": "", "tutar": tutar, "esik": None,
                    "gecerlilik_baslangic": tarih, "gecerlilik_bitis": None,
                    "nakliyeci": "OMSAN", "motorin_fiyati": motorin,
                    "aciklama": "Tarifede olmayan mesafe için km başına.",
                })
            continue

        if operasyon not in OUTBOUND_OPERASYONLARI:
            continue
        cikis = CIKIS_NOKTALARI.get(yer_adi(yukleme))
        cozum = _varisi_coz(varis)
        if not cikis or not cozum:
            continue
        il, ilce = cozum
        for arac, fiyat in (("KAMYON", kamyon), ("TIR", tir)):
            if not fiyat:
                continue
            tarifeler.append({
                "sevkiyat_tipi": "FTL", "il": il, "ilce": ilce or "",
                "cikis_noktasi": cikis, "arac_tipi": arac,
                "desi_alt": None, "desi_ust": None, "birim_fiyat": fiyat,
                "gecerlilik_baslangic": tarih, "gecerlilik_bitis": None,
                "nakliyeci": "OMSAN", "para_birimi": "TRY",
                "motorin_fiyati": motorin,
                "aciklama": f"Omsan 2026 FTL · {yukleme} → {varis}",
            })
    return tarifeler, ek_ucretler, motorin, tarih


KADEMELER = ((0, 2000), (2001, 4000), (4001, None))


def parsiyel_oku(
    dosya: Path, motorin: Decimal | None, tarih: date
) -> tuple[list[dict], list[dict]]:
    sayfa = load_workbook(dosya, read_only=True, data_only=True).worksheets[0]
    satirlar = list(sayfa.iter_rows(values_only=True))

    asgari: list[dict] = []
    basliк = satirlar[0]
    esik = 50
    tutar = next((_ondalik(h) for h in basliк if isinstance(h, (int, float))), None)
    if tutar:
        asgari.append({
            "tur": "ASGARI_GONDERI", "sevkiyat_tipi": "RUTIN", "arac_tipi": "",
            "cikis_noktasi": "", "tutar": tutar, "esik": esik,
            "gecerlilik_baslangic": tarih, "gecerlilik_bitis": None,
            "nakliyeci": "OMSAN", "motorin_fiyati": motorin,
            "aciklama": "Minimum gönderi bedeli (1-50 desi arası), Türkiye geneli.",
        })

    tarifeler: list[dict] = []
    for satir in satirlar[3:]:
        cikis = CIKIS_NOKTALARI.get(yer_adi(satir[1]))
        if not cikis:
            continue  # inbound satırı: yükleme noktası il adı
        cozum = _varisi_coz(satir[2])
        if not cozum:
            continue
        il, ilce = cozum
        for (alt, ust), hucre in zip(KADEMELER, satir[3:6]):
            fiyat = _ondalik(hucre)
            if not fiyat:
                continue
            tarifeler.append({
                "sevkiyat_tipi": "RUTIN", "il": il, "ilce": ilce or "",
                "cikis_noktasi": cikis, "arac_tipi": "",
                "desi_alt": alt, "desi_ust": ust, "birim_fiyat": fiyat,
                "gecerlilik_baslangic": tarih, "gecerlilik_bitis": None,
                "nakliyeci": "OMSAN", "para_birimi": "TRY",
                "motorin_fiyati": motorin,
                "aciklama": f"Omsan parsiyel · {satir[1]} → {satir[2]}",
            })
    return tarifeler, asgari


def il_genel_satirlarini_tamamla(tarifeler: list[dict]) -> list[dict]:
    """İlçe kırılımı olan iller için ilin genel satırını üretir.

    Planın ilçesi bilinmiyorsa ya da listede olmayan bir ilçeyse maliyet yine de
    hesaplanabilmeli. Genel satır varyantların **en yükseğidir**: hangi yakaya
    gittiği bilinmeyen bir aracı düşük fiyatlamak, maliyet kontrolünde yüksek
    fiyatlamaktan daha yanıltıcı olurdu.
    """
    gruplar: dict[tuple, list[dict]] = {}
    for tarife in tarifeler:
        if not tarife["ilce"]:
            continue
        anahtar = (
            tarife["sevkiyat_tipi"], tarife["il"], tarife["cikis_noktasi"],
            tarife["arac_tipi"], tarife["desi_alt"], tarife["desi_ust"],
        )
        gruplar.setdefault(anahtar, []).append(tarife)

    genel = []
    for anahtar, grup in gruplar.items():
        if any(
            not t["ilce"] and (
                t["sevkiyat_tipi"], t["il"], t["cikis_noktasi"], t["arac_tipi"],
                t["desi_alt"], t["desi_ust"],
            ) == anahtar
            for t in tarifeler
        ):
            continue
        en_yuksek = max(grup, key=lambda t: t["birim_fiyat"])
        varyantlar = ", ".join(sorted(t["ilce"] for t in grup))
        genel.append({
            **en_yuksek, "ilce": "",
            "aciklama": (
                f"İlçesi bilinmeyen sevkiyat için genel satır; sözleşmede "
                f"{varyantlar} ayrı fiyatlı, buraya en yükseği yazıldı."
            ),
        })
    return genel


def main() -> None:
    argumanlar = list(sys.argv[1:])
    gecerlilik = None
    if "--gecerlilik" in argumanlar:
        indeks = argumanlar.index("--gecerlilik")
        gecerlilik = date.fromisoformat(argumanlar[indeks + 1])
        del argumanlar[indeks:indeks + 2]
    if len(argumanlar) < 2:
        raise SystemExit(__doc__)
    ftl_dosyasi, parsiyel_dosyasi = Path(argumanlar[0]), Path(argumanlar[1])
    for dosya in (ftl_dosyasi, parsiyel_dosyasi):
        if not dosya.exists():
            raise SystemExit(f"Bulunamadı: {dosya}")

    ftl, ftl_ek, motorin, liste_tarihi = ftl_oku(ftl_dosyasi)
    tarih = gecerlilik or liste_tarihi
    if gecerlilik and gecerlilik != liste_tarihi:
        # Liste yıl ortasında revize edilmiş; geçmiş sevkleri değerlemek için
        # başlangıç geriye çekiliyor. Bu bir varsayımdır ve açıklamaya yazılır.
        for kayit in ftl + ftl_ek:
            kayit["gecerlilik_baslangic"] = tarih
            kayit["aciklama"] = (
                f"{kayit['aciklama']} · {liste_tarihi:%d.%m.%Y} listesi, "
                f"{tarih:%d.%m.%Y} tarihinden geçerli sayıldı"
            )
    parsiyel, parsiyel_ek = parsiyel_oku(parsiyel_dosyasi, motorin, tarih)
    if gecerlilik and gecerlilik != liste_tarihi:
        for kayit in parsiyel + parsiyel_ek:
            kayit["aciklama"] = (
                f"{kayit['aciklama']} · {liste_tarihi:%d.%m.%Y} listesi, "
                f"{tarih:%d.%m.%Y} tarihinden geçerli sayıldı"
            )
    tarifeler = ftl + parsiyel
    tarifeler += il_genel_satirlarini_tamamla(tarifeler)
    ek_ucretler = ftl_ek + parsiyel_ek

    print(f"Motorin: {motorin} · liste tarihi: {liste_tarihi:%d.%m.%Y} "
          f"· geçerlilik: {tarih:%d.%m.%Y}")
    print(f"FTL tarifesi: {len(ftl)} · parsiyel tarifesi: {len(parsiyel)}")
    print(f"İl genel satırı: {len(tarifeler) - len(ftl) - len(parsiyel)}")
    print(f"Ek ücret: {len(ek_ucretler)}")

    kitap = yeni_kitap()
    sayfa = kitap.create_sheet("Tarifeler")
    sayfa_yaz(
        sayfa,
        [alan.baslik for alan in TARIFE_ALANLARI],
        [[t.get(alan.ad) for alan in TARIFE_ALANLARI] for t in tarifeler],
    )
    sayfa.auto_filter.ref = sayfa.dimensions

    ek = kitap.create_sheet("Ek Ücretler")
    sayfa_yaz(
        ek,
        [alan.baslik for alan in EK_UCRET_ALANLARI],
        [[u.get(alan.ad) for alan in EK_UCRET_ALANLARI] for u in ek_ucretler],
    )

    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(HEDEF)
    print(f"\nYazıldı: {HEDEF}")


if __name__ == "__main__":
    main()
