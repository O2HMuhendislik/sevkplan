"""Excel okuma/yazma yardımcıları.

Kolon başlıkları normalize edilerek eşleştirilir: büyük/küçük harf, Türkçe karakter,
boşluk ve alt çizgi farkları tolere edilir. Böylece kaynak sistemden gelen dosyanın
başlıkları birebir aynı yazılmak zorunda kalmaz.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_TR_HARFLER = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")

BASLIK_DOLGU = PatternFill("solid", fgColor="1F4E79")
BASLIK_YAZI = Font(color="FFFFFF", bold=True)


def normalize(metin: Any) -> str:
    if metin is None:
        return ""
    return (
        str(metin).translate(_TR_HARFLER).strip().lower().replace(" ", "_").replace("-", "_")
    )


class ExcelHatasi(Exception):
    pass


def satirlari_oku(
    dosya: Path | Any, alias_haritasi: dict[str, tuple[str, ...]]
) -> list[dict[str, Any]]:
    """İlk sayfayı okuyup her satırı normalize alan adlarıyla sözlüğe çevirir.

    `alias_haritasi`: {alan_adi: (kabul edilen başlık varyantları, ...)}
    """
    calisma_kitabi = load_workbook(dosya, data_only=True, read_only=True)
    sayfa = calisma_kitabi.worksheets[0]
    satir_iter = sayfa.iter_rows(values_only=True)
    try:
        basliklar = [normalize(h) for h in next(satir_iter)]
    except StopIteration:
        raise ExcelHatasi("Dosya boş.") from None

    kolon_indeksi: dict[str, int] = {}
    for alan, aliaslar in alias_haritasi.items():
        aday_setleri = {normalize(a) for a in aliaslar} | {alan}
        for idx, baslik in enumerate(basliklar):
            if baslik in aday_setleri:
                kolon_indeksi[alan] = idx
                break

    kayitlar: list[dict[str, Any]] = []
    for satir_no, satir in enumerate(satir_iter, start=2):
        if satir is None or all(h is None or str(h).strip() == "" for h in satir):
            continue
        kayit: dict[str, Any] = {"_satir_no": satir_no}
        for alan, idx in kolon_indeksi.items():
            kayit[alan] = satir[idx] if idx < len(satir) else None
        kayitlar.append(kayit)
    calisma_kitabi.close()
    return kayitlar


def eksik_kolonlar(
    dosya: Path | Any, alias_haritasi: dict[str, tuple[str, ...]], zorunlu: tuple[str, ...]
) -> list[str]:
    calisma_kitabi = load_workbook(dosya, data_only=True, read_only=True)
    basliklar = {
        normalize(h) for h in next(calisma_kitabi.worksheets[0].iter_rows(values_only=True), ())
    }
    calisma_kitabi.close()
    eksikler = []
    for alan in zorunlu:
        adaylar = {normalize(a) for a in alias_haritasi.get(alan, ())} | {alan}
        if not (adaylar & basliklar):
            eksikler.append(alan)
    return eksikler


def metin(deger: Any) -> str | None:
    if deger is None:
        return None
    sonuc = str(deger).strip()
    if sonuc.endswith(".0") and sonuc[:-2].isdigit():
        sonuc = sonuc[:-2]  # Excel sayısal hücreleri metne çevirirken oluşan .0 kuyruğu
    return sonuc or None


def sayi(deger: Any, alan: str) -> Decimal:
    if deger is None or str(deger).strip() == "":
        raise ExcelHatasi(f"{alan} boş olamaz")
    try:
        return Decimal(str(deger).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ExcelHatasi(f"{alan} sayı olmalı: {deger!r}") from None


def tam_sayi(deger: Any, alan: str) -> int:
    return int(sayi(deger, alan))


def tarih(deger: Any) -> date | None:
    if deger is None or str(deger).strip() == "":
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    ham = str(deger).strip()
    for desen in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%Y%m%d"):
        try:
            return datetime.strptime(ham, desen).date()
        except ValueError:
            continue
    raise ExcelHatasi(f"Tarih çözümlenemedi: {deger!r} (beklenen: GG.AA.YYYY)")


def evet_hayir(deger: Any, varsayilan: bool = False) -> bool:
    if deger is None or str(deger).strip() == "":
        return varsayilan
    return normalize(deger) in {"e", "evet", "h_evet", "1", "true", "x", "var", "yes"}


def sayfa_yaz(
    sayfa, basliklar: list[str], satirlar: list[list[Any]], genislikler: list[int] | None = None
) -> None:
    sayfa.append(basliklar)
    for hucre in sayfa[1]:
        hucre.fill = BASLIK_DOLGU
        hucre.font = BASLIK_YAZI
        hucre.alignment = Alignment(horizontal="center", vertical="center")
    for satir in satirlar:
        sayfa.append(satir)
    for idx, baslik in enumerate(basliklar, start=1):
        genislik = genislikler[idx - 1] if genislikler else max(14, len(str(baslik)) + 4)
        sayfa.column_dimensions[get_column_letter(idx)].width = genislik
    sayfa.freeze_panes = "A2"


def yeni_kitap() -> Workbook:
    kitap = Workbook()
    kitap.remove(kitap.active)
    return kitap
