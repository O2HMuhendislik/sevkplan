"""Yükleme formu (depo operasyona gidecek Excel çıktısı).

DİKKAT — GEÇİCİ DÜZEN: Nihai yükleme formu formatı henüz iletilmedi. Aşağıdaki
düzen, formdaki bilgi ihtiyacını karşılayan geçici bir taslaktır. Gerçek şablon
geldiğinde yalnızca bu modül değişecek; plan verisi ve iş kuralları etkilenmeyecek.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl.styles import Alignment, Border, Font, Side

from app.config import CIKTI_DIZIN
from app.models import SevkiyatPlani
from app.services.excel import sayfa_yaz, yeni_kitap

BASLIK_FONT = Font(bold=True, size=14)
ETIKET_FONT = Font(bold=True)
INCE_KENAR = Border(*[Side(style="thin")] * 4)

SATIR_BASLIKLARI = [
    "Sıra", "Teslimat No", "Sipariş No", "Müşteri", "Ürün Kodu", "Ürün Adı",
    "Miktar", "Birim", "Palet", "Termin",
]


def form_uret(plan: SevkiyatPlani, hedef: Path | None = None) -> Path:
    from app.services.plan_servisi import teslimatlari_hazirla  # döngüsel import önlemi

    kitap = yeni_kitap()
    sayfa = kitap.create_sheet("Yükleme Formu")

    sayfa["A1"] = "YÜKLEME FORMU"
    sayfa["A1"].font = BASLIK_FONT
    ustbilgi = [
        ("Sefer No", plan.sefer_no),
        ("Axata İş Emri No", plan.axata_no or "— GİRİLMEDİ —"),
        ("Plan Tarihi", plan.plan_tarihi.strftime("%d.%m.%Y") if plan.plan_tarihi else ""),
        ("Depo Kodu", plan.depo_kodu),
        ("Plan Tipi", "Mix Plan" if plan.mix_mi else plan.plan_tipi),
        ("Toplam Palet", f"{plan.toplam_palet} / 20"),
        ("Doluluk", f"%{plan.doluluk_yuzdesi}"),
        ("Teslimat Sayısı", plan.teslimat_sayisi),
        ("Ürün(ler)", plan.urun_kodlari),
        ("Yazdırma Zamanı", datetime.now().strftime("%d.%m.%Y %H:%M")),
    ]
    for idx, (etiket, deger) in enumerate(ustbilgi, start=3):
        sayfa.cell(row=idx, column=1, value=etiket).font = ETIKET_FONT
        sayfa.cell(row=idx, column=2, value=deger)
    if plan.istisna_asim:
        uyari = sayfa.cell(
            row=len(ustbilgi) + 3,
            column=1,
            value="DİKKAT: Tek teslimat 20 palet üst limitini aşıyor (istisna planı).",
        )
        uyari.font = Font(bold=True, color="C00000")

    baslangic = len(ustbilgi) + 5
    satirlar = []
    for sira, satir in enumerate(
        sorted(plan.satirlar, key=lambda s: (s.teslimat_no, s.siparis_satir_no)), start=1
    ):
        satirlar.append([
            sira,
            satir.teslimat_no,
            f"{satir.siparis_no} / {satir.siparis_satir_no}",
            satir.musteri_adi or satir.musteri_kodu or "",
            satir.urun_kodu,
            satir.urun_adi or "",
            float(satir.miktar),
            satir.birim_kodu,
            "",  # palet kırılımı teslimat bazında hesaplanır, aşağıda doldurulur
            satir.termin_tarihi.strftime("%d.%m.%Y") if satir.termin_tarihi else "",
        ])

    for idx, baslik in enumerate(SATIR_BASLIKLARI, start=1):
        hucre = sayfa.cell(row=baslangic, column=idx, value=baslik)
        hucre.font = ETIKET_FONT
        hucre.border = INCE_KENAR
        hucre.alignment = Alignment(horizontal="center")
    for satir_idx, satir in enumerate(satirlar, start=baslangic + 1):
        for kolon_idx, deger in enumerate(satir, start=1):
            hucre = sayfa.cell(row=satir_idx, column=kolon_idx, value=deger)
            hucre.border = INCE_KENAR

    toplam_satir = baslangic + len(satirlar) + 1
    sayfa.cell(row=toplam_satir, column=6, value="TOPLAM PALET").font = ETIKET_FONT
    sayfa.cell(row=toplam_satir, column=9, value=float(plan.toplam_palet)).font = ETIKET_FONT

    imza_satir = toplam_satir + 3
    for kolon, etiket in enumerate(("Hazırlayan", "Depo Sorumlusu", "Şoför / Forklift Op."), start=1):
        sayfa.cell(row=imza_satir, column=kolon * 2 - 1, value=etiket).font = ETIKET_FONT
        sayfa.cell(row=imza_satir + 1, column=kolon * 2 - 1, value="..........................")

    for kolon, genislik in zip("ABCDEFGHIJ", (10, 18, 22, 30, 18, 34, 12, 10, 10, 14)):
        sayfa.column_dimensions[kolon].width = genislik

    hedef = hedef or CIKTI_DIZIN / f"yukleme_formu_{plan.sefer_no}.xlsx"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(hedef)
    return hedef


def plan_listesi_disa_aktar(planlar: list[SevkiyatPlani], hedef: Path) -> Path:
    """Rapor ekranlarındaki plan listesini Excel'e aktarır."""
    kitap = yeni_kitap()
    sayfa = kitap.create_sheet("Planlar")
    basliklar = [
        "Sefer No", "Plan Tarihi", "Durum", "Axata No", "Depo", "Ürün(ler)",
        "Teslimat Sayısı", "Toplam Palet", "Doluluk %", "Mix", "İstisna",
        "Mail Tarihi", "Oluşturan",
    ]
    satirlar = [
        [
            plan.sefer_no,
            plan.plan_tarihi.strftime("%d.%m.%Y") if plan.plan_tarihi else "",
            plan.durum.value,
            plan.axata_no or "",
            plan.depo_kodu,
            plan.urun_kodlari,
            plan.teslimat_sayisi,
            float(plan.toplam_palet or Decimal(0)),
            float(plan.doluluk_yuzdesi or Decimal(0)),
            "E" if plan.mix_mi else "H",
            "E" if plan.istisna_asim else "H",
            plan.mail_gonderim_tarihi.strftime("%d.%m.%Y %H:%M") if plan.mail_gonderim_tarihi else "",
            plan.olusturan,
        ]
        for plan in planlar
    ]
    sayfa_yaz(sayfa, basliklar, satirlar)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    kitap.save(hedef)
    return hedef
