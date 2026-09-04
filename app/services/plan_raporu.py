"""Modülden bağımsız plan raporu: özet, ürün grubu kırılımı, plan listesi, sevk durumu.

Üç modülün de (Ring, İç Piyasa, İhracat) plan ekranından aynı rapor alınır; hangi
modülün planları olduğunu `modul` belirler, verilmezse hepsi tek kitapta toplanır.

Kitap dört sayfadan oluşur:

* **Özet** — modül ve duruma göre plan sayıları, ortalama doluluk, toplam adet.
* **Ürün Grubu** — planlanan ürünlerin grup bazında toplam adedi; "bu dönem hangi
  gruptan kaç adet sevk planına girdi" sorusunun cevabı.
* **Planlar** — her planın tek satırlık künyesi (sefer, tarih, doluluk, araç, rota).
* **Sevk Durumu** — aynı planların operasyon takibi: Axata, araç/plaka, mail, durum
  geçişleri ve planın kaç gün önce açıldığı.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl.styles import Alignment, Font

from app.config import CIKTI_DIZIN
from app.models import PlanDurumu, SevkiyatPlani
from app.services.excel import BASLIK_DOLGU, BASLIK_YAZI, yeni_kitap

MODUL_ADLARI = {
    "RING": "Ring",
    "ROTA": "İç Piyasa",
    "IHRACAT": "İhracat",
}

BASLIK_YAZISI = Font(bold=True, size=12)


def _tarih(deger: date | datetime | None) -> str:
    return deger.strftime("%d.%m.%Y") if deger else ""


def _sayi(deger) -> float:
    return float(deger or 0)


def _sayfa_yaz(kitap, ad: str, basliklar: list[str], satirlar: list[list], genislikler=None):
    sayfa = kitap.create_sheet(ad)
    sayfa.append(basliklar)
    for hucre in sayfa[1]:
        hucre.fill = BASLIK_DOLGU
        hucre.font = BASLIK_YAZI
        hucre.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for satir in satirlar:
        sayfa.append(satir)
    for sira, baslik in enumerate(basliklar, start=1):
        harf = sayfa.cell(row=1, column=sira).column_letter
        sayfa.column_dimensions[harf].width = (
            genislikler[sira - 1] if genislikler else max(12, min(42, len(baslik) + 6))
        )
    sayfa.freeze_panes = "A2"
    sayfa.auto_filter.ref = sayfa.dimensions
    return sayfa


def _ozet_satirlari(planlar: list[SevkiyatPlani]) -> list[list]:
    """Modül × durum kırılımı; son satır genel toplam."""
    gruplar: dict[tuple[str, str], list[SevkiyatPlani]] = defaultdict(list)
    for plan in planlar:
        gruplar[(plan.modul or "-", plan.durum.value)].append(plan)

    satirlar = []
    for (modul, durum), grup in sorted(gruplar.items()):
        satirlar.append(_ozet_satiri(MODUL_ADLARI.get(modul, modul), durum, grup))
    if planlar:
        satirlar.append(_ozet_satiri("TOPLAM", "—", planlar))
    return satirlar


def _ozet_satiri(modul: str, durum: str, grup: list[SevkiyatPlani]) -> list:
    doluluklar = [Decimal(p.doluluk_yuzdesi or 0) for p in grup]
    return [
        modul,
        durum,
        len(grup),
        sum(p.teslimat_sayisi or 0 for p in grup),
        round(sum(_sayi(p.toplam_adet) for p in grup), 2),
        round(sum(_sayi(p.toplam_palet) for p in grup), 2),
        round(sum(_sayi(p.toplam_agirlik) for p in grup), 2),
        round(float(sum(doluluklar) / len(doluluklar)), 2) if doluluklar else 0.0,
    ]


def _urun_grubu_satirlari(planlar: list[SevkiyatPlani]) -> list[list]:
    """Planlanan ürünlerin modül + grup bazında toplamı."""
    toplamlar: dict[tuple[str, str], dict] = {}
    for plan in planlar:
        modul = MODUL_ADLARI.get(plan.modul or "-", plan.modul or "-")
        for kayit in plan.urun_grubu_ozeti:
            hedef = toplamlar.setdefault(
                (modul, kayit["grup"]),
                {"adet": Decimal(0), "teslimat": 0, "planlar": set()},
            )
            hedef["adet"] += kayit["adet"]
            hedef["teslimat"] += kayit["teslimat"]
            hedef["planlar"].add(plan.id)
    satirlar = [
        [modul, grup, len(deger["planlar"]), deger["teslimat"], float(deger["adet"])]
        for (modul, grup), deger in toplamlar.items()
    ]
    satirlar.sort(key=lambda s: (s[0], -s[4]))
    if satirlar:
        satirlar.append([
            "TOPLAM", "—",
            len({p.id for p in planlar}),
            sum(s[3] for s in satirlar),
            round(sum(s[4] for s in satirlar), 2),
        ])
    return satirlar


def _plan_satirlari(planlar: list[SevkiyatPlani]) -> list[list]:
    return [
        [
            sira,
            MODUL_ADLARI.get(plan.modul or "-", plan.modul or "-"),
            plan.sefer_no,
            _tarih(plan.plan_tarihi),
            plan.durum.value,
            plan.sevkiyat_tipi or plan.arac_tipi or "",
            plan.depo_kodu,
            plan.yukleme_deposu or "",
            plan.musteri_adi or plan.planlama_anahtari or "",
            plan.ulke or plan.iller_metni or "",
            plan.durak_sayisi or 0,
            plan.teslimat_sayisi or 0,
            _sayi(plan.toplam_adet),
            round(_sayi(plan.toplam_palet), 2),
            round(_sayi(plan.toplam_desi), 2),
            round(_sayi(plan.toplam_agirlik), 2),
            round(_sayi(plan.doluluk_yuzdesi), 2),
            plan.kisitlayan_olcu or "",
            "E" if plan.alt_limit_esnetildi else "",
            "E" if plan.istisna_asim else "",
            plan.marka_ozeti,
            plan.urun_kodlari or "",
            plan.olusturan,
        ]
        for sira, plan in enumerate(planlar, start=1)
    ]


def _sevk_durumu_satirlari(planlar: list[SevkiyatPlani]) -> list[list]:
    bugun = date.today()
    return [
        [
            sira,
            MODUL_ADLARI.get(plan.modul or "-", plan.modul or "-"),
            plan.sefer_no,
            _tarih(plan.plan_tarihi),
            plan.durum.value,
            plan.axata_ozeti or "",
            plan.nakliyeci or "",
            plan.plaka or "",
            plan.konteyner_no or "",
            plan.muhur_no or "",
            plan.surucu or "",
            plan.surucu_telefon or "",
            _tarih(plan.mail_gonderim_tarihi),
            _tarih(plan.olusturma_tarihi),
            (bugun - plan.plan_tarihi).days if plan.plan_tarihi else "",
            plan.iptal_aciklamasi or plan.musteri_aciklamasi or "",
        ]
        for sira, plan in enumerate(planlar, start=1)
    ]


def rapor_uret(
    planlar: list[SevkiyatPlani], hedef: Path | None = None, modul: str | None = None
) -> Path:
    """Plan raporunu üretir. `modul` yalnızca dosya adı ve başlık içindir."""
    ad = MODUL_ADLARI.get(modul or "", "tum-moduller").lower().replace(" ", "-")
    hedef = hedef or CIKTI_DIZIN / f"plan_raporu_{ad}.xlsx"

    # İptal edilen planlar sevk edilmiş işi temsil etmiyor; özet onları saymaz ama
    # listede kalırlar ki neyin iptal olduğu da görünsün.
    canli = [p for p in planlar if p.durum is not PlanDurumu.IPTAL]

    kitap = yeni_kitap()
    _sayfa_yaz(
        kitap, "Özet",
        ["Modül", "Durum", "Plan", "Teslimat", "Toplam Adet", "Toplam Palet",
         "Toplam Ağırlık (kg)", "Ort. Doluluk %"],
        _ozet_satirlari(canli),
    )
    _sayfa_yaz(
        kitap, "Ürün Grubu",
        ["Modül", "Ürün Grubu", "Plan Sayısı", "Teslimat", "Planlanan Adet"],
        _urun_grubu_satirlari(canli),
        genislikler=[16, 26, 14, 12, 18],
    )
    _sayfa_yaz(
        kitap, "Planlar",
        ["#", "Modül", "Sefer No", "Plan Tarihi", "Durum", "Tip / Araç", "Depo",
         "Yükleme Deposu", "Müşteri / Anahtar", "İl / Ülke", "Durak", "Teslimat",
         "Toplam Adet", "Palet", "Desi", "Ağırlık (kg)", "Doluluk %", "Kısıtlayan",
         "Alt Limit Esnetildi", "İstisna", "Marka Payı", "Ürünler", "Oluşturan"],
        _plan_satirlari(planlar),
        genislikler=[5, 12, 14, 12, 16, 14, 8, 14, 30, 18, 8, 10, 13, 10, 12, 13,
                     11, 12, 10, 9, 26, 40, 14],
    )
    _sayfa_yaz(
        kitap, "Sevk Durumu",
        ["#", "Modül", "Sefer No", "Plan Tarihi", "Durum", "Axata", "Nakliyeci",
         "Plaka", "Konteyner No", "Mühür No", "Şoför", "Telefon", "Mail Tarihi",
         "Oluşturma", "Bugüne Kalan Gün", "Açıklama"],
        _sevk_durumu_satirlari(planlar),
        genislikler=[5, 12, 14, 12, 16, 16, 20, 14, 16, 14, 18, 14, 12, 12, 14, 40],
    )

    hedef.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(hedef)
    return hedef


def bekleyen_raporu(satirlar, hedef: Path, modul: str | None = None) -> Path:
    """Plana giremeyen sipariş satırlarını Excel'e aktarır.

    Beklemede (hacim bekliyor) ve hatalı (master datası eksik) satırlar bir arada,
    sebep sütunuyla; planlamacı hangi eksiği tamamlayacağını buradan görür.
    """
    kitap = yeni_kitap()
    _sayfa_yaz(
        kitap, "Bekleyen Siparişler",
        ["#", "Modül", "Durum", "Teslimat", "Sipariş", "Bayi", "İl", "İlçe", "Depo",
         "Ürün Kodu", "Ürün Adı", "Adet", "Termin", "Bekleme (gün)", "Sebep"],
        [
            [
                sira,
                MODUL_ADLARI.get(satir.modul or "-", satir.modul or "-"),
                satir.durum.value,
                satir.teslimat_no,
                satir.siparis_no,
                satir.bayi_gosterimi,
                satir.sehir or "",
                satir.ilce or "",
                satir.depo_kodu,
                satir.urun_kodu,
                satir.gosterilecek_urun_adi,
                _sayi(satir.miktar),
                _tarih(satir.termin_tarihi),
                satir.bekleme_gunu,
                satir.hata_aciklamasi or "Hacim bekliyor",
            ]
            for sira, satir in enumerate(satirlar, start=1)
        ],
        genislikler=[5, 12, 12, 16, 16, 30, 14, 14, 8, 14, 34, 10, 12, 13, 46],
    )
    hedef.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(hedef)
    return hedef
