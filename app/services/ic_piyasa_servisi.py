"""İç piyasa plan üretimi: veritabanı ile planlama motoru arasındaki köprü.

Ring servisinden ayrı durur çünkü planlamanın birimi farklıdır: Ring'de teslimat,
burada **müşteri**. Sevkiyat tipi (FTL / rutin / kargo) müşterinin o günkü toplam
siparişine bakılarak belirlendiği için teslimatlar önce müşteri altında toplanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Collection

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import sefer_no as sefer_no_modulu
from app.domain.bolgeler import bolge_adi
from app.domain.ic_piyasa import (
    BekleyenMusteri,
    Kurallar,
    MusteriSiparisi,
    RotaPlani,
    SevkiyatTipi,
    VARSAYILAN_KURALLAR,
    planla,
    tip_belirle,
    yukleme_deposu,
)
from app.domain.iller import yer_adi
from app.domain.kapasite import (
    IC_FTL,
    IC_FTL_KAMYON,
    IC_KARGO,
    IC_RUTIN,
    IC_RUTIN_KAMYON,
    KapasiteProfili,
)
from app.domain.marka import paylari_hesapla, paylari_metne_cevir
from app.models import (
    Musteri,
    PlanDurumu,
    PlanHareketi,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)
from app.services.plan_servisi import (
    PlanHatasi,
    palet_haritasi,
    sonraki_sefer_no,
    teslimatlari_hazirla,
    yukleme_haritasi,
)

MODUL_KODU = "ROTA"

TIP_PROFILLERI: dict[SevkiyatTipi, KapasiteProfili] = {
    SevkiyatTipi.FTL: IC_FTL,
    SevkiyatTipi.RUTIN: IC_RUTIN,
    SevkiyatTipi.KARGO: IC_KARGO,
}

KAMYON_PROFILLERI: dict[SevkiyatTipi, KapasiteProfili] = {
    SevkiyatTipi.FTL: IC_FTL_KAMYON,
    SevkiyatTipi.RUTIN: IC_RUTIN_KAMYON,
}
"""Aynı tipin kamyon karşılığı. Kargoda araç yoktur, o yüzden listede değildir."""


def profil(tip: SevkiyatTipi) -> KapasiteProfili:
    return TIP_PROFILLERI[tip]


def kamyon_profili(tip: SevkiyatTipi) -> KapasiteProfili | None:
    return KAMYON_PROFILLERI.get(tip)


@dataclass
class IcPlanSonucu:
    planlar: list[SevkiyatPlani] = field(default_factory=list)
    bekleyenler: list[BekleyenMusteri] = field(default_factory=list)
    hatali_teslimatlar: list[tuple[str, str]] = field(default_factory=list)
    musteri_sayisi: int = 0
    tip_dagilimi: dict[str, int] = field(default_factory=dict)

    def ozet(self) -> str:
        """Planlama sonucu. Tip dağılımı hem müşteri hem araç sayısını gösterir.

        Eskiden yalnızca müşteri sayısı yazıyordu; "Rutin / parsiyel: 18" görüp
        18 araç sanılıyordu, oysa o 18 müşteri tek araca binmiş olabilir.
        """
        arac_sayilari: dict[str, int] = {}
        for plan in self.planlar:
            anahtar = plan.sevkiyat_tipi or ""
            arac_sayilari[anahtar] = arac_sayilari.get(anahtar, 0) + 1
        dagilim = " · ".join(
            f"{SevkiyatTipi(tip).ad}: {adet} müşteri / "
            f"{arac_sayilari.get(tip, 0)} araç"
            for tip, adet in sorted(self.tip_dagilimi.items())
        )
        metin = (
            f"{self.musteri_sayisi} müşteri değerlendirildi · "
            f"{len(self.planlar)} plan üretildi · "
            f"{len(self.bekleyenler)} müşteri beklemede · "
            f"{len(self.hatali_teslimatlar)} teslimat hatalı"
        )
        return f"{metin} · {dagilim}" if dagilim else metin


# ---------------------------------------------------------------- müşteri toplama


def _bayi_anahtari(satir: SiparisSatiri) -> str:
    """Bayiyi tekilleştiren değer; müşteri master datasıyla eşleşme buradan kurulur.

    Bayi adı yoksa alıcı firma, o da yoksa teslimat numarası kullanılır: anahtarsız
    satırların tek bir "boş müşteri" altında birleşip yanlış araç kurması engellenir.
    """
    return (
        yer_adi(satir.bayi_adi)
        or yer_adi(satir.alici_firma)
        or f"TESLIMAT:{satir.teslimat_no}"
    )


def _durak_adi(satir: SiparisSatiri) -> str:
    """Ekranda ve yükleme formunda görünecek durak adı.

    Kaynak dosyada bayi adı boş gelebiliyor; o zaman alıcı firma, o da yoksa açık
    adres kullanılır. Teslimat numarası ad yerine geçmez — ekranda "TESLIMAT:2013…"
    yazması bilgi vermiyor.
    """
    return (
        (satir.bayi_adi or "").strip()
        or (satir.alici_firma or "").strip()
        or (satir.sevk_adresi or "").strip()
        or "(bayi adı yok)"
    )


def _durak_anahtari(satir: SiparisSatiri) -> str:
    """Planlamanın birimi: bir **teslimat noktası** (bayi + il + ilçe).

    Aynı bayi adı birden çok ilde şube taşıyabiliyor (bayi kodu gelmediği için hepsi
    tek adla geliyor). Yalnızca ada göre gruplarsak Ankara, Samsun ve Trabzon'daki üç
    şube tek durak sayılır; araç tek duraklı görünür, son uğrak ve "Yer Miktarı" yanlış
    çıkar. Bu yüzden anahtar il ve ilçeyi de içerir.
    """
    il = yer_adi(satir.sehir)
    ilce = yer_adi(satir.ilce)
    return f"{_bayi_anahtari(satir)}|{il}|{ilce}"


def musterileri_topla(
    db: Session,
    satirlar: list[SiparisSatiri],
    hedef_profil: KapasiteProfili = IC_FTL,
) -> tuple[list[MusteriSiparisi], list[tuple[str, str]]]:
    """Sipariş satırlarını müşteri bazında toplar.

    Ölçüler (palet, anahtar değer) teslimat bazında hesaplanır; müşteri düzeyinde
    toplanırken kırık paletler **birleştirilmez**, çünkü her teslimat ayrı adrese iner.
    """
    teslimatlar, hatalilar, urun_haritasi = teslimatlari_hazirla(
        db, satirlar, hedef_profil, "SKU"
    )
    satir_haritasi = {satir.id: satir for satir in satirlar}
    desi_haritasi = {
        kod: Decimal(urun.desi) for kod, urun in urun_haritasi.items() if urun.desi
    }

    musteri_kayitlari = {
        m.anahtar: m for m in db.scalars(select(Musteri)).all()
    }

    gruplar: dict[str, list] = {}
    for teslimat in teslimatlar:
        ana_satir = satir_haritasi[teslimat.satir_idleri[0]]
        gruplar.setdefault(_durak_anahtari(ana_satir), []).append(teslimat)

    musteriler: list[MusteriSiparisi] = []
    for anahtar, grup in sorted(gruplar.items()):
        ilk = satir_haritasi[grup[0].satir_idleri[0]]
        kayit = musteri_kayitlari.get(_bayi_anahtari(ilk))

        desi = Decimal(0)
        for teslimat in grup:
            for sku, miktar in teslimat.sku_miktarlari.items():
                desi += desi_haritasi.get(sku, Decimal(0)) * miktar

        # İl ve ilçe siparişin kendisinden gelir; durak anahtarı da bunlarla kuruldu.
        # Master data yalnızca sipariş satırında boş kalan alanı doldurur.
        il = yer_adi(ilk.sehir) or (kayit.il if kayit else "") or ""
        ilce = yer_adi(ilk.ilce) or (kayit.ilce if kayit else "") or ""
        incoterms = (
            (kayit.incoterms if kayit and kayit.incoterms else ilk.incoterms) or ""
        ).upper()

        musteriler.append(
            MusteriSiparisi(
                anahtar=anahtar,
                bayi_adi=_durak_adi(ilk),
                il=il,
                ilce=ilce,
                teslimatlar=tuple(grup),
                palet=sum((t.palet for t in grup), Decimal(0)),
                birim=sum((t.birim for t in grup), Decimal(0)),
                # Araç tipi yükleme bittikten sonra seçildiği için kamyon ölçüsü de
                # baştan taşınır; bir SKU'nun kamyon adedi yoksa kamyon elenir.
                kamyon_birim=sum((t.kamyon_anahtar for t in grup), Decimal(0)),
                kamyon_uygun=all(t.kamyon_olculebilir for t in grup),
                desi=desi.quantize(Decimal("0.001")),
                adet=sum((t.miktar for t in grup), Decimal(0)),
                agirlik=sum((t.agirlik for t in grup), Decimal(0)),
                incoterms=incoterms,
                tir_girisi=kayit.tir_girisi if kayit else "?",
            )
        )
    return musteriler, hatalilar


def _gunluk_plan_sayisi(db: Session, plan_tarihi: date, tip: SevkiyatTipi) -> int:
    """O gün için zaten üretilmiş (iptal edilmemiş) plan sayısı."""
    return (
        db.scalar(
            select(func.count(SevkiyatPlani.id)).where(
                SevkiyatPlani.modul == MODUL_KODU,
                SevkiyatPlani.plan_tarihi == plan_tarihi,
                SevkiyatPlani.sevkiyat_tipi == tip.value,
                SevkiyatPlani.durum != PlanDurumu.IPTAL,
            )
        )
        or 0
    )


def _gunluk_sinir(
    db: Session, plan_tarihi: date, tip: SevkiyatTipi, kurallar: Kurallar
) -> int | None:
    """O gün için kalan araç hakkı. Kargoda sınır yoktur."""
    if tip is SevkiyatTipi.KARGO:
        return None
    tavan = (
        kurallar.gunluk_ftl_siniri
        if tip is SevkiyatTipi.FTL
        else kurallar.gunluk_rutin_siniri
    )
    return max(0, tavan - _gunluk_plan_sayisi(db, plan_tarihi, tip))


# --------------------------------------------------------------------- plan üretimi


def plan_uret(
    db: Session,
    plan_tarihi: date | None = None,
    tipler: list[SevkiyatTipi] | None = None,
    kullanici: str = "sistem",
    kalanlari_zorla: bool = False,
    kurallar: Kurallar = VARSAYILAN_KURALLAR,
    depolar: list[str] | None = None,
    teslimat_nolar: Collection[str] | None = None,
) -> IcPlanSonucu:
    """Beklemedeki iç piyasa siparişlerinden plan üretir.

    `tipler` verilmezse üç tip de çalıştırılır. Sevkiyat tipi müşteri bazında
    belirlenir; kullanıcının seçtiği tipler yalnızca **hangi kovaların planlanacağını**
    sınırlar, müşterinin tipini değiştirmez.

    `teslimat_nolar` verilirse yalnızca o teslimatlar planlanır; manuel planlama
    ekranı (/rota/manuel-plan) seçilen siparişleri böyle geçirir.
    """
    plan_tarihi = plan_tarihi or date.today()
    tipler = tipler or list(SevkiyatTipi)

    sorgu = select(SiparisSatiri).where(
        SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE,
        SiparisSatiri.plan_id.is_(None),
        SiparisSatiri.modul == MODUL_KODU,
    )
    if depolar:
        sorgu = sorgu.where(SiparisSatiri.depo_kodu.in_(depolar))
    satirlar = list(db.scalars(sorgu).all())
    if teslimat_nolar is not None:
        secilenler = {str(no).strip() for no in teslimat_nolar if str(no).strip()}
        satirlar = [satir for satir in satirlar if satir.teslimat_no in secilenler]

    musteriler, hatalilar = musterileri_topla(db, satirlar)
    sonuc = IcPlanSonucu(
        hatali_teslimatlar=hatalilar, musteri_sayisi=len(musteriler)
    )
    if not musteriler:
        db.flush()
        return sonuc

    kovalar: dict[SevkiyatTipi, list[MusteriSiparisi]] = {t: [] for t in SevkiyatTipi}
    gerekceler: dict[str, str] = {}
    for musteri in musteriler:
        tip, gerekce = tip_belirle(musteri, kurallar)
        kovalar[tip].append(musteri)
        gerekceler[musteri.anahtar] = gerekce
    sonuc.tip_dagilimi = {
        tip.value: len(grup) for tip, grup in kovalar.items() if grup
    }

    # Bayi ortak deposu teslimatlarını araç kapasitesine göre kesebilmek için
    # ürünlerin palet ve yükleme adetleri gerekiyor.
    urunler = {
        urun.urun_kodu: urun
        for urun in db.scalars(
            select(Urun).where(
                Urun.urun_kodu.in_({s.urun_kodu for s in satirlar})
            )
        ).all()
    }
    palet_haritasi_ = palet_haritasi(urunler)
    yukleme_haritasi_ = yukleme_haritasi(urunler, IC_FTL.arac_tipi)
    # Tır giremeyen müşterinin yükü kamyon kapasitesine göre bölünür.
    kamyon_yukleme_haritasi_ = yukleme_haritasi(urunler, IC_FTL_KAMYON.arac_tipi)

    satir_haritasi = {satir.id: satir for satir in satirlar}
    for tip in tipler:
        grup = kovalar[tip]
        if not grup:
            continue
        tip_profili = profil(tip)
        planlama = planla(
            grup,
            tip,
            tip_profili,
            kurallar,
            gunluk_sinir=_gunluk_sinir(db, plan_tarihi, tip, kurallar),
            kalanlari_zorla=kalanlari_zorla,
            palet_ici=palet_haritasi_,
            yukleme_adeti=yukleme_haritasi_,
            kamyon_profili=kamyon_profili(tip),
            kamyon_yukleme_adeti=kamyon_yukleme_haritasi_,
        )
        for taslak in planlama.planlar:
            sonuc.planlar.append(
                _plani_kaydet(
                    db, taslak, satir_haritasi, plan_tarihi,
                    taslak.secili_profil, kullanici,
                )
            )
        sonuc.bekleyenler.extend(planlama.bekleyenler)

    # Kullanıcının seçmediği tiplerdeki müşteriler de gerekçesiyle raporlanır.
    for tip, grup in kovalar.items():
        if tip in tipler:
            continue
        for musteri in grup:
            sonuc.bekleyenler.append(
                BekleyenMusteri(
                    musteri=musteri,
                    tip=tip,
                    sebep=f"{tip.ad} bu çalıştırmada seçilmedi — {gerekceler[musteri.anahtar]}",
                )
            )

    db.flush()
    return sonuc


def _plani_kaydet(
    db: Session,
    taslak: RotaPlani,
    satir_haritasi: dict[int, SiparisSatiri],
    plan_tarihi: date,
    kapasite: KapasiteProfili,
    kullanici: str,
) -> SevkiyatPlani:
    sefer = sonraki_sefer_no(db, plan_tarihi, kapasite.belge_kodu)
    depolar = taslak.depolar
    yukleme = yukleme_deposu(taslak) or (depolar[0] if depolar else "")
    urun_kodlari = sorted({kod for t in taslak.teslimatlar for kod in t.kodlar})

    plan = SevkiyatPlani(
        sefer_no=sefer,
        donem=sefer_no_modulu.donem_anahtari(plan_tarihi),
        plan_tipi=kapasite.kod,
        modul=MODUL_KODU,
        sevkiyat_tipi=taslak.tip.value,
        depo_kodu=yukleme,
        yukleme_deposu=yukleme,
        planlama_anahtari=bolge_adi(taslak.bolge_kodu),
        bolge_kodu=taslak.bolge_kodu,
        urun_kodlari=", ".join(urun_kodlari)[:500],
        olcu=kapasite.olcu.value,
        # Araç tipi yükleme bittikten sonra seçilir: yarım kalan tır, dolu kamyondur.
        arac_tipi=taslak.arac_tipi.value,
        toplam_birim=taslak.secili_birim,
        toplam_palet=taslak.toplam_palet,
        toplam_anahtar=taslak.secili_birim,
        toplam_adet=taslak.toplam_adet,
        toplam_agirlik=taslak.toplam_agirlik,
        toplam_desi=taslak.toplam_desi,
        doluluk_yuzdesi=taslak.doluluk_yuzdesi,
        teslimat_sayisi=len(taslak.teslimatlar),
        musteri_sayisi=taslak.durak_sayisi,
        durak_sayisi=taslak.durak_sayisi,
        iller_metni=", ".join(taslak.iller)[:400],
        ilceler_metni=", ".join(taslak.ilceler)[:600],
        son_ugrak=taslak.son_ugrak,
        son_ugrak_orani=taslak.son_ugrak_orani.quantize(
            Decimal("0.0001"), ROUND_HALF_UP
        ),
        marka_paylari_metni=paylari_metne_cevir(paylari_hesapla(taslak.depo_katkilari))
        or None,
        istisna_asim=taslak.istisna_asim,
        alt_limit_esnetildi=taslak.alt_limit_esnetildi,
        durum=PlanDurumu.TASLAK,
        plan_tarihi=plan_tarihi,
        olusturan=kullanici,
    )
    db.add(plan)
    db.flush()

    bolunen_satir = 0
    for teslimat in taslak.teslimatlar:
        for satir_id in teslimat.satir_idleri:
            satir = satir_haritasi[satir_id]
            _, alinan = teslimat.satir_miktarlari.get(satir_id, (None, None))
            if alinan is not None and alinan < Decimal(satir.miktar):
                satir = _satiri_ayir(db, satir, alinan)
                bolunen_satir += 1
            satir.plan_id = plan.id
            satir.durum = SiparisDurumu.PLANLANDI

    notlar = [
        f"{kapasite.bicimle(taslak.toplam_birim)} · "
        f"{taslak.durak_sayisi} durak · {len(taslak.teslimatlar)} teslimat"
    ]
    if len(depolar) > 1:
        notlar.append(
            "Ortak yükleme: " + ", ".join(depolar) + f" → {yukleme} deposundan"
        )
    if taslak.tir_giremeyen_musteriler:
        notlar.append(
            "Tır giremeyen müşteri: "
            + ", ".join(m.bayi_adi for m in taslak.tir_giremeyen_musteriler)
        )
    if bolunen_satir:
        notlar.append(
            f"{bolunen_satir} satır araç kapasitesine göre bölündü; kalan miktar "
            "aynı teslimat numarasıyla beklemede"
        )
    if taslak.alt_limit_esnetildi:
        notlar.append("alt limit esnetildi")
    if taslak.istisna_asim:
        notlar.append("üst limit istisnası")

    db.add(
        PlanHareketi(
            plan=plan,
            onceki_durum=None,
            yeni_durum=PlanDurumu.TASLAK.value,
            aciklama=" · ".join(notlar),
            kullanici=kullanici,
        )
    )
    return plan


def _satiri_ayir(
    db: Session, satir: SiparisSatiri, alinan: Decimal
) -> SiparisSatiri:
    """Satırın `alinan` kadarını yeni bir satıra ayırır; kalan orijinalde bekler.

    Bayi ortak deposu (-1) siparişleri araç kapasitesine göre bölünebiliyor. Bölünen
    parça **aynı teslimat ve sipariş numarasını** taşır — ERP tarafında bölünme de
    böyle görünüyor; ayırt etmek için satır numarasına sıra eki verilir.
    """
    alinan = min(Decimal(alinan), Decimal(satir.miktar))
    kalan = Decimal(satir.miktar) - alinan
    satir.miktar = kalan

    kok = satir.siparis_satir_no.split("#")[0]
    mevcut_ekler = {
        s.siparis_satir_no
        for s in db.scalars(
            select(SiparisSatiri).where(
                SiparisSatiri.siparis_no == satir.siparis_no,
                SiparisSatiri.teslimat_no == satir.teslimat_no,
            )
        ).all()
    }
    sira = 2
    while f"{kok}#{sira}" in mevcut_ekler:
        sira += 1

    yeni = SiparisSatiri(
        siparis_no=satir.siparis_no,
        siparis_satir_no=f"{kok}#{sira}",
        teslimat_no=satir.teslimat_no,
        urun_kodu=satir.urun_kodu,
        urun_adi=satir.urun_adi,
        miktar=alinan,
        depo_kodu=satir.depo_kodu,
        sehir=satir.sehir,
        bayi_adi=satir.bayi_adi,
        alici_firma=satir.alici_firma,
        sevk_adresi=satir.sevk_adresi,
        teslim_sekli=satir.teslim_sekli,
        incoterms=satir.incoterms,
        ilce=satir.ilce,
        siparis_tarihi=satir.siparis_tarihi,
        termin_tarihi=satir.termin_tarihi,
        durum=SiparisDurumu.BEKLEMEDE,
        modul=satir.modul,
        ice_aktarim_id=satir.ice_aktarim_id,
        olusturma_tarihi=satir.olusturma_tarihi,
    )
    db.add(yeni)
    db.flush()
    return yeni


def plan_musterileri(db: Session, plan: SevkiyatPlani) -> list[dict]:
    """Plan detay ekranı için durak listesi: müşteri, il, ilçe, hacim, aktarma notu.

    Kaydedilmiş plandan yeniden türetilir; motorun `RotaPlani` nesnesi saklanmıyor.
    Tır girişi bilgisi müşteri master datasından okunur — tır giremeyen bir adres
    plana düşmüşse ekranda uyarı çıkması için.
    """
    from app.domain.iller import mesafe

    anahtarlar = {_bayi_anahtari(satir) for satir in plan.satirlar}
    kayitlar = {
        m.anahtar: m
        for m in db.scalars(
            select(Musteri).where(Musteri.anahtar.in_(anahtarlar))
        ).all()
    }

    gruplar: dict[str, dict] = {}
    for satir in plan.satirlar:
        anahtar = _durak_anahtari(satir)
        kayit = kayitlar.get(_bayi_anahtari(satir))
        durak = gruplar.setdefault(
            anahtar,
            {
                "bayi_adi": _durak_adi(satir),
                "il": yer_adi(satir.sehir),
                "ilce": yer_adi(satir.ilce),
                "tir_girisi": kayit.tir_girisi if kayit else "?",
                "adet": Decimal(0),
                "teslimatlar": set(),
                "depolar": set(),
                "aktarma_notu": "",
            },
        )
        durak["adet"] += Decimal(satir.miktar)
        durak["teslimatlar"].add(satir.teslimat_no)
        durak["depolar"].add(satir.depo_kodu)
        not_metni = plan.aktarma_notu(satir)
        if not_metni:
            durak["aktarma_notu"] = not_metni

    duraklar = list(gruplar.values())
    duraklar.sort(
        key=lambda d: (
            mesafe(d["il"]) if mesafe(d["il"]) is not None else 9999,
            d["il"],
            d["bayi_adi"],
        )
    )
    for sira, durak in enumerate(duraklar, start=1):
        durak["sira"] = sira
        durak["teslimat_sayisi"] = len(durak["teslimatlar"])
        durak["depo_metni"] = ", ".join(sorted(durak["depolar"]))
    return duraklar


def musteri_ozeti(db: Session, satirlar: list[SiparisSatiri]) -> list[dict]:
    """Sipariş ekranında "bu müşteri hangi tiple gider" önizlemesi."""
    musteriler, _ = musterileri_topla(db, satirlar)
    ozet = []
    for musteri in musteriler:
        tip, gerekce = tip_belirle(musteri)
        ozet.append(
            {
                "bayi_adi": musteri.bayi_adi,
                "il": musteri.il,
                "ilce": musteri.ilce,
                "bolge": bolge_adi(musteri.bolge_kodu),
                "palet": musteri.palet,
                "anahtar": musteri.birim,
                "desi": musteri.desi,
                "adet": musteri.adet,
                "incoterms": musteri.incoterms,
                "tir_girisi": musteri.tir_girisi,
                "tip": tip,
                "gerekce": gerekce,
                "teslimat_sayisi": len(musteri.teslimatlar),
                "depolar": ", ".join(sorted(musteri.depolar)),
            }
        )
    ozet.sort(key=lambda o: (o["tip"].value, -o["anahtar"], o["bayi_adi"]))
    return ozet


def arac_bilgisi_kaydet(
    db: Session,
    plan: SevkiyatPlani,
    nakliyeci: str | None,
    plaka: str | None,
    surucu: str | None,
    surucu_telefon: str | None,
    kullanici: str = "sistem",
) -> None:
    """Yükleme formunun araç bloğunu doldurur."""
    if plan.durum in {PlanDurumu.IPTAL, PlanDurumu.TAMAMLANDI}:
        raise PlanHatasi(
            f"{plan.sefer_no} {plan.durum.value} durumunda, değiştirilemez."
        )
    plan.nakliyeci = (nakliyeci or "").strip() or None
    plan.plaka = (plaka or "").strip() or None
    plan.surucu = (surucu or "").strip() or None
    plan.surucu_telefon = (surucu_telefon or "").strip() or None
    db.add(
        PlanHareketi(
            plan=plan,
            onceki_durum=plan.durum.value,
            yeni_durum=plan.durum.value,
            aciklama=(
                "Araç bilgisi: "
                + " · ".join(
                    parca
                    for parca in (plan.nakliyeci, plan.plaka, plan.surucu)
                    if parca
                )
            ),
            kullanici=kullanici,
        )
    )
    db.flush()
