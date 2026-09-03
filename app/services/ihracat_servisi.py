"""İhracat plan üretimi: veritabanı ile ihracat planlama motoru arasındaki köprü.

İç piyasadan farkı: araç tek noktaya gider, aracın doluluğu şirketin `Hesaplama.xlsx`
formülüyle ölçülür (Σ miktar / yükleme adeti), ağırlık ikinci sınır olarak durur ve
sefer numarasının belge kodu müşteriye göre N ya da E olur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import sefer_no as sefer_no_modulu
from app.domain.ihracat import (
    AracTipi,
    BekleyenYuk,
    IhracatPlani,
    Kurallar,
    MusteriYuku,
    VARSAYILAN_KURALLAR,
    planla,
)
from app.domain.ihracat_hesap import Kalem, UrunOlcusu, hesapla, yukleme_kurali_coz
from app.domain.iller import yer_adi
from app.domain.marka import paylari_hesapla, paylari_metne_cevir
from app.domain.planlama import Teslimat
from app.models import (
    IhracatMusterisi,
    IhracatUrunu,
    PlanDurumu,
    PlanHareketi,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
)
from app.services.plan_servisi import PlanHatasi, sonraki_sefer_no

MODUL_KODU = "IHRACAT"


@dataclass
class IhracatPlanSonucu:
    planlar: list[SevkiyatPlani] = field(default_factory=list)
    bekleyenler: list[BekleyenYuk] = field(default_factory=list)
    musteri_sayisi: int = 0
    tanimsiz_musteriler: list[str] = field(default_factory=list)
    """Master datada bulunamayan müşteriler; varsayılan tır kuralıyla planlandılar."""

    def ozet(self) -> str:
        metin = (
            f"{self.musteri_sayisi} müşteri değerlendirildi · "
            f"{len(self.planlar)} araç planlandı · "
            f"{len(self.bekleyenler)} müşteri beklemede"
        )
        if self.tanimsiz_musteriler:
            metin += (
                f" · {len(self.tanimsiz_musteriler)} müşteri master datada yok, "
                "tır varsayıldı"
            )
        return metin


def urun_olculeri(db: Session) -> dict[str, UrunOlcusu]:
    """İhracat ürün master datasını kod -> ölçü sözlüğüne çevirir."""
    return {u.urun_kodu: u.olcu for u in db.scalars(select(IhracatUrunu)).all()}


def musteri_yuklerini_topla(
    db: Session, satirlar: list[SiparisSatiri]
) -> tuple[list[MusteriYuku], list[str]]:
    """Sipariş satırlarını müşteri bazında toplar ve doluluklarını hesaplar.

    Doluluk ürün master datasından gelir: her SKU'nun tırı ve konteyneri dolduran
    adedi bellidir, aracın doluluğu bu payların toplamıdır. Müşterinin hesap sürümü
    (yeni/eski) ve palet yükseltmesi master datadaki yükleme tipi ile notlardan
    çözülür. Master datada olmayan SKU'lar için dosyadaki desi kullanılır.
    """
    kayitlar = {
        m.anahtar: m for m in db.scalars(select(IhracatMusterisi)).all()
    }
    olculer = urun_olculeri(db)

    gruplar: dict[str, list[SiparisSatiri]] = {}
    for satir in satirlar:
        gruplar.setdefault(yer_adi(satir.bayi_adi), []).append(satir)

    yukler: list[MusteriYuku] = []
    tanimsizlar: list[str] = []
    for anahtar, grup in sorted(gruplar.items()):
        if not anahtar:
            continue
        kayit = kayitlar.get(anahtar)
        if kayit is None:
            tanimsizlar.append(grup[0].bayi_adi or anahtar)

        tip = (
            AracTipi(kayit.arac_tipi) if kayit and kayit.arac_tipi else AracTipi.TIR
        )
        kural = (
            kayit.yukleme_kurali
            if kayit is not None
            else yukleme_kurali_coz("", "")
        )

        # Teslimat, planlamanın bölünmez birimidir; satırlar teslimata göre toplanır.
        teslimat_gruplari: dict[str, list[SiparisSatiri]] = {}
        for satir in grup:
            teslimat_gruplari.setdefault(satir.teslimat_no, []).append(satir)

        teslimatlar: list[Teslimat] = []
        olcusuzler: list[str] = []
        for teslimat_no, satirlari in sorted(teslimat_gruplari.items()):
            kalemler = [
                Kalem(
                    urun_kodu=s.urun_kodu,
                    miktar=Decimal(s.miktar),
                    olcu=olculer.get(s.urun_kodu),
                    desi=Decimal(s.desi or 0),
                    agirlik=Decimal(s.agirlik or 0),
                )
                for s in satirlari
            ]
            olcu = hesapla(kalemler, tip.value, kural)
            olcusuzler.extend(olcu.olcusuz_kodlar)
            teslimatlar.append(
                Teslimat(
                    teslimat_no=teslimat_no,
                    depo_kodu=satirlari[0].depo_kodu,
                    planlama_anahtari=satirlari[0].urun_kodu,
                    urun_kodu=satirlari[0].urun_kodu,
                    urun_adi=satirlari[0].urun_adi or "",
                    miktar=sum((Decimal(s.miktar) for s in satirlari), Decimal(0)),
                    # İhracatta kapasite ölçüsü doluluktur; `birim` ve `anahtar` onu taşır.
                    birim=olcu.doluluk or Decimal("0.000001"),
                    anahtar=olcu.doluluk,
                    oncelik_tarihi=min(s.oncelik_tarihi for s in satirlari),
                    satir_idleri=tuple(s.id for s in satirlari),
                    sku_kodlari=tuple(sorted({s.urun_kodu for s in satirlari})),
                    depo_katkilari={satirlari[0].depo_kodu: olcu.doluluk},
                    agirlik=olcu.agirlik,
                    desi=olcu.desi,
                    palet=olcu.palet,
                )
            )

        ilk = grup[0]
        yukler.append(
            MusteriYuku(
                anahtar=anahtar,
                musteri_adi=ilk.bayi_adi or anahtar,
                ulke=(kayit.ulke if kayit and kayit.ulke else ilk.sehir) or "",
                ulke_kodu=(
                    kayit.ulke_kodu if kayit and kayit.ulke_kodu else ilk.ulke_kodu
                ) or "",
                sevk_adresi=(
                    ilk.sevk_adresi or (kayit.sevk_adresi if kayit else "")
                ) or "",
                teslimatlar=tuple(teslimatlar),
                doluluk=sum((t.anahtar for t in teslimatlar), Decimal(0)),
                desi=sum((t.desi for t in teslimatlar), Decimal(0)),
                agirlik=sum((t.agirlik for t in teslimatlar), Decimal(0)),
                adet=sum((t.miktar for t in teslimatlar), Decimal(0)),
                palet=sum((t.palet for t in teslimatlar), Decimal(0)),
                kural=kural,
                olcusuz_kodlar=tuple(dict.fromkeys(olcusuzler)),
                arac_tipi=tip,
                sefer_kodu=(kayit.sefer_kodu if kayit else "E") or "E",
                yukleme_tipi=(kayit.yukleme_tipi if kayit else "") or "",
                aciklama=(kayit.aciklama if kayit else "") or "",
                azami_agirlik=(
                    Decimal(kayit.azami_agirlik)
                    if kayit and kayit.azami_agirlik
                    else None
                ),
                incoterms=(
                    kayit.incoterms if kayit and kayit.incoterms else ilk.incoterms
                ) or "",
            )
        )
    return yukler, tanimsizlar


def plan_uret(
    db: Session,
    plan_tarihi: date | None = None,
    kullanici: str = "sistem",
    kalanlari_zorla: bool = False,
    kurallar: Kurallar = VARSAYILAN_KURALLAR,
) -> IhracatPlanSonucu:
    """Beklemedeki ihracat siparişlerinden araç planı üretir."""
    plan_tarihi = plan_tarihi or date.today()
    satirlar = list(
        db.scalars(
            select(SiparisSatiri).where(
                SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE,
                SiparisSatiri.plan_id.is_(None),
                SiparisSatiri.modul == MODUL_KODU,
            )
        ).all()
    )

    yukler, tanimsizlar = musteri_yuklerini_topla(db, satirlar)
    sonuc = IhracatPlanSonucu(
        musteri_sayisi=len(yukler), tanimsiz_musteriler=tanimsizlar
    )
    if not yukler:
        db.flush()
        return sonuc

    planlama = planla(yukler, kurallar, kalanlari_zorla)
    satir_haritasi = {satir.id: satir for satir in satirlar}
    for taslak in planlama.planlar:
        sonuc.planlar.append(
            _plani_kaydet(db, taslak, satir_haritasi, plan_tarihi, kullanici)
        )
    sonuc.bekleyenler = planlama.bekleyenler
    db.flush()
    return sonuc


def _plani_kaydet(
    db: Session,
    taslak: IhracatPlani,
    satir_haritasi: dict[int, SiparisSatiri],
    plan_tarihi: date,
    kullanici: str,
) -> SevkiyatPlani:
    musteri = taslak.musteri
    profil = taslak.profil
    # Belge kodu profilden değil müşteriden gelir: N (NSC) ya da E (Export).
    sefer = sonraki_sefer_no(db, plan_tarihi, musteri.sefer_kodu)
    depolar = taslak.depolar
    urun_kodlari = sorted({kod for t in taslak.teslimatlar for kod in t.kodlar})

    plan = SevkiyatPlani(
        sefer_no=sefer,
        donem=sefer_no_modulu.donem_anahtari(plan_tarihi),
        plan_tipi=profil.kod,
        modul=MODUL_KODU,
        sevkiyat_tipi=musteri.arac_tipi.value,
        depo_kodu=depolar[0] if depolar else "",
        yukleme_deposu=depolar[0] if depolar else "",
        planlama_anahtari=musteri.musteri_adi[:50],
        musteri_adi=musteri.musteri_adi,
        ulke=musteri.ulke,
        ulke_kodu=musteri.ulke_kodu,
        arac_tipi=musteri.arac_tipi.value,
        tasima_modu=musteri.arac_tipi.tasima_modu,
        yukleme_tipi=musteri.yukleme_tipi or None,
        musteri_aciklamasi=musteri.aciklama or None,
        azami_agirlik=musteri.agirlik_kapasitesi,
        kisitlayan_olcu=taslak.kisitlayan,
        urun_kodlari=", ".join(urun_kodlari)[:500],
        olcu=profil.olcu.value,
        toplam_birim=taslak.hacim,
        toplam_palet=taslak.palet,
        toplam_desi=taslak.desi,
        toplam_agirlik=taslak.agirlik,
        toplam_adet=taslak.adet,
        doluluk_yuzdesi=taslak.doluluk_yuzdesi,
        teslimat_sayisi=len(taslak.teslimatlar),
        musteri_sayisi=1,
        durak_sayisi=1,
        iller_metni=musteri.ulke,
        son_ugrak=musteri.ulke,
        son_ugrak_orani=Decimal(1),
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

    for teslimat in taslak.teslimatlar:
        for satir_id in teslimat.satir_idleri:
            satir = satir_haritasi[satir_id]
            satir.plan_id = plan.id
            satir.durum = SiparisDurumu.PLANLANDI

    notlar = [
        f"{musteri.arac_tipi.ad} · %{taslak.doluluk_yuzdesi} "
        f"({taslak.kisitlayan} sınırı) · "
        f"{taslak.palet.quantize(Decimal('0.1'))} palet · "
        f"{taslak.desi.quantize(Decimal(1))} desi · "
        f"{taslak.agirlik.quantize(Decimal(1))} kg",
        f"Hesap: {musteri.kural.ad}",
    ]
    if musteri.olcusuz_kodlar:
        # Bu SKU'ların yükleme adeti master datada yok; doluluk desiden yaklaşıldı.
        ornek = ", ".join(musteri.olcusuz_kodlar[:5])
        notlar.append(
            f"{len(musteri.olcusuz_kodlar)} ürünün yükleme adeti master datada yok "
            f"({ornek}); doluluk desiden yaklaşık hesaplandı"
        )
    if len(depolar) > 1:
        notlar.append("Ortak yükleme: " + ", ".join(depolar))
    if musteri.yukleme_tipi:
        notlar.append(f"Yükleme tipi: {musteri.yukleme_tipi}")
    if taslak.istisna_asim:
        notlar.append("üst limit istisnası: tek teslimat aracı aşıyor")
    if taslak.alt_limit_esnetildi:
        notlar.append("alt limit esnetildi")

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


def musteri_onizlemesi(db: Session, satirlar: list[SiparisSatiri]) -> list[dict]:
    """Sipariş ekranındaki "bu müşteri hangi araçla gider" önizlemesi."""
    yukler, tanimsizlar = musteri_yuklerini_topla(db, satirlar)
    tanimsiz_kumesi = {yer_adi(ad) for ad in tanimsizlar}
    ozet = []
    for yuk in yukler:
        profil = yuk.profil
        hacim = (yuk.doluluk / profil.ust_limit) if profil.ust_limit else Decimal(0)
        agirlik = (
            (yuk.agirlik / yuk.agirlik_kapasitesi)
            if yuk.agirlik_kapasitesi
            else Decimal(0)
        )
        ozet.append(
            {
                "musteri_adi": yuk.musteri_adi,
                "ulke": yuk.ulke,
                "ulke_kodu": yuk.ulke_kodu,
                "arac_tipi": yuk.arac_tipi,
                "tasima_modu": yuk.arac_tipi.tasima_modu,
                "sefer_kodu": yuk.sefer_kodu,
                "yukleme_tipi": yuk.yukleme_tipi,
                "hesaplama": yuk.kural.ad,
                "palet": yuk.palet.quantize(Decimal("0.1")),
                "desi": yuk.desi.quantize(Decimal(1)),
                "agirlik": yuk.agirlik.quantize(Decimal(1)),
                "adet": yuk.adet,
                "teslimat_sayisi": len(yuk.teslimatlar),
                "arac_sayisi": max(1, -(-int(max(hacim, agirlik) * 100) // 100)),
                "doluluk": (max(hacim, agirlik) * 100).quantize(
                    Decimal("0.1"), ROUND_HALF_UP
                ),
                "kisitlayan": "AĞIRLIK" if agirlik > hacim else "HACİM",
                "master_datada_yok": yer_adi(yuk.musteri_adi) in tanimsiz_kumesi,
                "olcusuz_sayisi": len(yuk.olcusuz_kodlar),
                "aciklama": yuk.aciklama,
            }
        )
    ozet.sort(key=lambda o: (o["ulke"], -o["doluluk"]))
    return ozet


def arac_bilgisi_kaydet(
    db: Session,
    plan: SevkiyatPlani,
    nakliyeci: str | None,
    plaka: str | None,
    konteyner_no: str | None,
    muhur_no: str | None,
    surucu: str | None,
    kullanici: str = "sistem",
) -> None:
    """Yükleme formunun araç bloğunu doldurur (çekici, dorse/konteyner, mühür)."""
    if plan.durum in {PlanDurumu.IPTAL, PlanDurumu.TAMAMLANDI}:
        raise PlanHatasi(
            f"{plan.sefer_no} {plan.durum.value} durumunda, değiştirilemez."
        )
    plan.nakliyeci = (nakliyeci or "").strip() or None
    plan.plaka = (plaka or "").strip() or None
    plan.konteyner_no = (konteyner_no or "").strip() or None
    plan.muhur_no = (muhur_no or "").strip() or None
    plan.surucu = (surucu or "").strip() or None
    db.add(
        PlanHareketi(
            plan=plan,
            onceki_durum=plan.durum.value,
            yeni_durum=plan.durum.value,
            aciklama="Araç bilgisi: "
            + " · ".join(
                parca
                for parca in (plan.nakliyeci, plan.plaka, plan.konteyner_no, plan.muhur_no)
                if parca
            ),
            kullanici=kullanici,
        )
    )
    db.flush()
