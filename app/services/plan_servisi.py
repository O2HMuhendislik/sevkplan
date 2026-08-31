"""Plan üretimi ve plan yaşam döngüsü servisleri."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import RING_DEPO_KODU, depo_profili
from app.domain import sefer_no as sefer_no_modulu
from app.domain.kapasite import RING_PALET, AracTipi, KapasiteProfili, Olcu
from app.domain.planlama import (
    BekleyenTeslimat,
    PlanlamaSonucu,
    TaslakPlan,
    Teslimat,
    palet_hesapla,
    planla,
)
from app.services.planlama_anahtari import teslimat_anahtari
from app.models import (
    PlanDurumu,
    PlanHareketi,
    SeferSayaci,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)


class PlanHatasi(Exception):
    """İş kuralı ihlali; kullanıcıya doğrudan gösterilir."""


@dataclass
class PlanUretimSonucu:
    planlar: list[SevkiyatPlani] = field(default_factory=list)
    bekleyenler: list[BekleyenTeslimat] = field(default_factory=list)
    hatali_teslimatlar: list[tuple[str, str]] = field(default_factory=list)
    degerlendirilen_teslimat: int = 0
    profil: KapasiteProfili | None = None

    def ozet(self) -> str:
        return (
            f"{self.degerlendirilen_teslimat} teslimat değerlendirildi · "
            f"{len(self.planlar)} plan üretildi · "
            f"{len(self.bekleyenler)} teslimat beklemede · "
            f"{len(self.hatali_teslimatlar)} teslimat hatalı"
        )


def sonraki_sefer_no(db: Session, plan_tarihi: date, belge_kodu: str) -> str:
    """Dönem sayacını bir artırıp sefer numarasını üretir.

    Sayaç her ay 1001'den başlar. Aynı transaction içinde okunup yazıldığı ve
    `sefer_no` alanında UNIQUE kısıt bulunduğu için mükerrer numara oluşamaz.
    """
    donem = sefer_no_modulu.donem_anahtari(plan_tarihi)
    sayac_kaydi = db.scalar(
        select(SeferSayaci)
        .where(SeferSayaci.donem == donem, SeferSayaci.belge_kodu == belge_kodu)
        .with_for_update()
    )
    yeni = sefer_no_modulu.uret(
        plan_tarihi, belge_kodu, sayac_kaydi.son_sayac if sayac_kaydi else None
    )
    if sayac_kaydi is None:
        db.add(SeferSayaci(donem=donem, belge_kodu=belge_kodu, son_sayac=yeni.sayac))
    else:
        sayac_kaydi.son_sayac = yeni.sayac
    db.flush()
    return str(yeni)


def _durum_degistir(
    db: Session,
    plan: SevkiyatPlani,
    yeni_durum: PlanDurumu,
    aciklama: str | None,
    kullanici: str,
) -> None:
    db.add(
        PlanHareketi(
            plan=plan,
            onceki_durum=plan.durum.value if plan.durum else None,
            yeni_durum=yeni_durum.value,
            aciklama=aciklama,
            kullanici=kullanici,
        )
    )
    plan.durum = yeni_durum


@dataclass
class TeslimatOlculeri:
    palet: Decimal
    anahtar: Decimal
    adet: Decimal
    agirlik: Decimal


def teslimat_olculeri(
    satirlar: list[SiparisSatiri],
    urun_haritasi: dict[str, Urun],
    arac_tipi: AracTipi,
) -> TeslimatOlculeri:
    """Bir teslimatın palet, anahtar, adet ve ağırlık toplamlarını hesaplar.

    Palet her SKU için ayrı yukarı yuvarlanır: kırık palet bir palet gözü kaplar ve
    aksesuarın palet içi adedi ana üründen farklıdır.
    """
    sku_miktarlari: dict[str, Decimal] = {}
    for satir in satirlar:
        sku_miktarlari[satir.urun_kodu] = (
            sku_miktarlari.get(satir.urun_kodu, Decimal(0)) + Decimal(satir.miktar)
        )

    palet = anahtar = agirlik = Decimal(0)
    for urun_kodu, miktar in sku_miktarlari.items():
        urun = urun_haritasi[urun_kodu]
        if urun.palet_ici_adet:
            palet += palet_hesapla(miktar, urun.palet_ici_adet)
        birim_anahtar = urun.anahtar_degeri(arac_tipi)
        if birim_anahtar is not None:
            anahtar += miktar * birim_anahtar
        if urun.agirlik:
            agirlik += miktar * Decimal(urun.agirlik)
    return TeslimatOlculeri(
        palet=palet,
        anahtar=anahtar.quantize(Decimal("0.000001")),
        adet=sum(sku_miktarlari.values(), Decimal(0)),
        agirlik=agirlik.quantize(Decimal("0.001")),
    )


def teslimatlari_hazirla(
    db: Session, satirlar: list[SiparisSatiri], profil: KapasiteProfili
) -> tuple[list[Teslimat], list[tuple[str, str]]]:
    """Sipariş satırlarını planlanabilir teslimatlara dönüştürür.

    Master datası eksik olan ya da kapasite ölçüsü için gerekli alanı bulunmayan
    teslimatlar planlamaya alınmaz; ilgili satırlar HATALI statüsüne çekilir.
    """
    urun_haritasi = {
        urun.urun_kodu: urun
        for urun in db.scalars(
            select(Urun).where(Urun.urun_kodu.in_({s.urun_kodu for s in satirlar}))
        ).all()
    }

    gruplar: dict[str, list[SiparisSatiri]] = {}
    for satir in satirlar:
        gruplar.setdefault(satir.teslimat_no, []).append(satir)

    teslimatlar: list[Teslimat] = []
    hatalilar: list[tuple[str, str]] = []

    for teslimat_no, grup in sorted(gruplar.items()):
        hata = None
        for satir in grup:
            urun = urun_haritasi.get(satir.urun_kodu)
            if urun is None:
                hata = f"{satir.urun_kodu} ürünü master datada tanımlı değil"
                break
            if not urun.aktif:
                hata = f"{satir.urun_kodu} ürünü pasif durumda"
                break
            if profil.olcu is Olcu.PALET and not urun.palet_ici_adet:
                hata = f"{satir.urun_kodu} için palet içi adet tanımsız"
                break
            if profil.olcu is Olcu.ANAHTAR and not urun.yukleme_adeti(profil.arac_tipi):
                hata = (
                    f"{satir.urun_kodu} için "
                    f"{profil.arac_tipi.value.lower()} yükleme adeti tanımsız"
                )
                break

        anahtar = teslimat_anahtari(urun_haritasi.get(s.urun_kodu) for s in grup)
        if hata is None and anahtar and " + " in anahtar:
            hata = f"Teslimat birden fazla ürün grubu içeriyor ({anahtar})"

        if hata is not None:
            for satir in grup:
                satir.durum = SiparisDurumu.HATALI
                satir.hata_aciklamasi = hata
            hatalilar.append((teslimat_no, hata))
            continue

        olculer = teslimat_olculeri(grup, urun_haritasi, profil.arac_tipi)
        birim = olculer.palet if profil.olcu is Olcu.PALET else olculer.anahtar
        if birim <= 0:
            hata = "Teslimatın kapasite büyüklüğü sıfır hesaplandı"
            for satir in grup:
                satir.durum = SiparisDurumu.HATALI
                satir.hata_aciklamasi = hata
            hatalilar.append((teslimat_no, hata))
            continue

        ana_satir = grup[0]
        ana_urun = urun_haritasi[ana_satir.urun_kodu]
        teslimatlar.append(
            Teslimat(
                teslimat_no=teslimat_no,
                depo_kodu=ana_satir.depo_kodu,
                planlama_anahtari=anahtar or ana_urun.urun_kodu,
                urun_kodu=ana_urun.urun_kodu,
                urun_adi=ana_urun.urun_adi,
                miktar=olculer.adet,
                birim=birim,
                oncelik_tarihi=min(s.oncelik_tarihi for s in grup),
                satir_idleri=tuple(s.id for s in grup),
                sku_kodlari=tuple(sorted({s.urun_kodu for s in grup})),
                palet=olculer.palet,
                anahtar=olculer.anahtar,
                agirlik=olculer.agirlik,
            )
        )
    return teslimatlar, hatalilar


def plan_uret(
    db: Session,
    plan_tarihi: date | None = None,
    depo_kodu: str = RING_DEPO_KODU,
    profil: KapasiteProfili | None = None,
    kullanici: str = "sistem",
) -> PlanUretimSonucu:
    """Beklemedeki siparişlerden taslak sevkiyat planları üretir.

    Kapasite profili depo koduna göre seçilir: 64 palet ölçüsüyle, 74 anahtar
    değerle planlanır (bkz. app/config.py DEPO_PROFILLERI).
    """
    plan_tarihi = plan_tarihi or date.today()
    profil = profil or depo_profili(depo_kodu)
    if profil is None:
        raise PlanHatasi(
            f"{depo_kodu} deposu için kapasite profili tanımlı değil. "
            "app/config.py içindeki DEPO_PROFILLERI listesine ekleyin."
        )

    satirlar = db.scalars(
        select(SiparisSatiri).where(
            SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE,
            SiparisSatiri.depo_kodu == depo_kodu,
            SiparisSatiri.plan_id.is_(None),
        )
    ).all()

    teslimatlar, hatalilar = teslimatlari_hazirla(db, list(satirlar), profil)
    sonuc = PlanUretimSonucu(
        hatali_teslimatlar=hatalilar,
        degerlendirilen_teslimat=len(teslimatlar),
        profil=profil,
    )
    if not teslimatlar:
        db.flush()
        return sonuc

    planlama: PlanlamaSonucu = planla(teslimatlar, profil)
    satir_haritasi = {satir.id: satir for satir in satirlar}

    for taslak in planlama.planlar:
        sonuc.planlar.append(
            _plani_kaydet(db, taslak, satir_haritasi, plan_tarihi, profil, kullanici)
        )
    sonuc.bekleyenler = planlama.bekleyenler
    db.flush()
    return sonuc


def _plani_kaydet(
    db: Session,
    taslak: TaslakPlan,
    satir_haritasi: dict[int, SiparisSatiri],
    plan_tarihi: date,
    profil: KapasiteProfili,
    kullanici: str,
    mix_mi: bool = False,
) -> SevkiyatPlani:
    sefer = sonraki_sefer_no(db, plan_tarihi, profil.belge_kodu)
    plan = SevkiyatPlani(
        sefer_no=sefer,
        donem=sefer_no_modulu.donem_anahtari(plan_tarihi),
        plan_tipi=profil.kod,
        depo_kodu=taslak.depo_kodu,
        planlama_anahtari=taslak.planlama_anahtari,
        urun_kodlari=", ".join(taslak.urun_kodlari),
        olcu=profil.olcu.value,
        toplam_birim=taslak.toplam_birim,
        toplam_palet=taslak.toplam_palet,
        toplam_anahtar=taslak.toplam_anahtar,
        toplam_adet=taslak.toplam_adet,
        toplam_agirlik=taslak.toplam_agirlik,
        doluluk_yuzdesi=taslak.doluluk_yuzdesi,
        teslimat_sayisi=len(taslak.teslimatlar),
        istisna_asim=taslak.istisna_asim,
        mix_mi=mix_mi,
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
    db.add(
        PlanHareketi(
            plan=plan,
            onceki_durum=None,
            yeni_durum=PlanDurumu.TASLAK.value,
            aciklama=(
                f"{profil.bicimle(taslak.toplam_birim)} · "
                f"{len(taslak.teslimatlar)} teslimat"
                + (" · üst limit istisnası" if taslak.istisna_asim else "")
            ),
            kullanici=kullanici,
        )
    )
    return plan


def mix_plan_olustur(
    db: Session,
    teslimat_nolar: list[str],
    plan_tarihi: date | None = None,
    profil: KapasiteProfili | None = None,
    kullanici: str = "sistem",
) -> SevkiyatPlani:
    """Manuel tetiklenen karma (farklı ürün gruplu) plan.

    Otomatik motor asla mix plan üretmez; bu yol yalnızca kullanıcı siparişleri
    seçip 'mix plan yap' dediğinde çalışır.
    """
    plan_tarihi = plan_tarihi or date.today()
    if not teslimat_nolar:
        raise PlanHatasi("En az bir teslimat seçilmeli.")

    satirlar = db.scalars(
        select(SiparisSatiri).where(SiparisSatiri.teslimat_no.in_(teslimat_nolar))
    ).all()
    if not satirlar:
        raise PlanHatasi("Seçilen teslimatlara ait sipariş satırı bulunamadı.")
    planli = [s.teslimat_no for s in satirlar if s.durum != SiparisDurumu.BEKLEMEDE]
    if planli:
        raise PlanHatasi(
            "Beklemede olmayan teslimatlar seçilemez: " + ", ".join(sorted(set(planli)))
        )

    depolar_ham = {s.depo_kodu for s in satirlar}
    if len(depolar_ham) > 1:
        raise PlanHatasi(
            f"Tek planda farklı depolar olamaz: {', '.join(sorted(depolar_ham))}"
        )
    profil = profil or depo_profili(next(iter(depolar_ham)))
    if profil is None:
        raise PlanHatasi(
            f"{next(iter(depolar_ham))} deposu için kapasite profili tanımlı değil."
        )

    teslimatlar, hatalilar = teslimatlari_hazirla(db, list(satirlar), profil)
    if hatalilar:
        raise PlanHatasi("; ".join(f"{no}: {mesaj}" for no, mesaj in hatalilar))

    toplam = sum((t.birim for t in teslimatlar), Decimal(0))
    if toplam > profil.ust_limit:
        raise PlanHatasi(
            f"Seçilen teslimatlar {profil.bicimle(toplam)} tutuyor, "
            f"üst limit {profil.bicimle(profil.ust_limit)}."
        )

    taslak = TaslakPlan(
        depo_kodu=teslimatlar[0].depo_kodu,
        planlama_anahtari="MIX",
        profil=profil,
        teslimatlar=teslimatlar,
    )
    satir_haritasi = {satir.id: satir for satir in satirlar}
    plan = _plani_kaydet(
        db, taslak, satir_haritasi, plan_tarihi, profil, kullanici, mix_mi=True
    )
    db.flush()
    return plan


def plan_onayla(db: Session, plan: SevkiyatPlani, kullanici: str = "sistem") -> None:
    if plan.durum != PlanDurumu.TASLAK:
        raise PlanHatasi(f"{plan.sefer_no} taslak değil, onaylanamaz.")
    _durum_degistir(db, plan, PlanDurumu.AXATA_BEKLIYOR, "Plan onaylandı", kullanici)
    db.flush()


def axata_no_gir(
    db: Session, plan: SevkiyatPlani, axata_no: str, kullanici: str = "sistem"
) -> None:
    axata_no = (axata_no or "").strip()
    if not axata_no:
        raise PlanHatasi("Axata numarası boş olamaz.")
    if plan.durum in {PlanDurumu.IPTAL, PlanDurumu.TAMAMLANDI}:
        raise PlanHatasi(f"{plan.sefer_no} {plan.durum.value} durumunda, değiştirilemez.")
    plan.axata_no = axata_no
    if plan.durum == PlanDurumu.TASLAK:
        _durum_degistir(
            db, plan, PlanDurumu.AXATA_BEKLIYOR, f"Axata no girildi: {axata_no}", kullanici
        )
    else:
        db.add(
            PlanHareketi(
                plan=plan,
                onceki_durum=plan.durum.value,
                yeni_durum=plan.durum.value,
                aciklama=f"Axata no güncellendi: {axata_no}",
                kullanici=kullanici,
            )
        )
    db.flush()


def mail_gonderildi_isaretle(
    db: Session, plan: SevkiyatPlani, kullanici: str = "sistem"
) -> None:
    """Yükleme formu depo operasyona iletildiğinde çağrılır.

    Axata numarası yükleme formunun zorunlu alanı olduğundan, numarası olmayan plan
    için mail gönderilemez.
    """
    if not plan.axata_no:
        raise PlanHatasi(
            f"{plan.sefer_no} için Axata iş emri numarası girilmeden mail gönderilemez."
        )
    if plan.durum not in {PlanDurumu.TASLAK, PlanDurumu.AXATA_BEKLIYOR, PlanDurumu.MAIL_GONDERILDI}:
        raise PlanHatasi(f"{plan.sefer_no} {plan.durum.value} durumunda, mail gönderilemez.")
    plan.mail_gonderim_tarihi = datetime.now()
    _durum_degistir(
        db, plan, PlanDurumu.MAIL_GONDERILDI, "Yükleme formu gönderildi", kullanici
    )
    db.flush()


def plan_tamamla(db: Session, plan: SevkiyatPlani, kullanici: str = "sistem") -> None:
    if plan.durum == PlanDurumu.IPTAL:
        raise PlanHatasi(f"{plan.sefer_no} iptal edilmiş, tamamlanamaz.")
    plan.tamamlanma_tarihi = datetime.now()
    _durum_degistir(db, plan, PlanDurumu.TAMAMLANDI, "Yükleme tamamlandı", kullanici)
    for satir in plan.satirlar:
        satir.durum = SiparisDurumu.TAMAMLANDI
    db.flush()


def plan_iptal(
    db: Session, plan: SevkiyatPlani, aciklama: str, kullanici: str = "sistem"
) -> None:
    """Planı iptal eder; siparişler beklemeye döner, sefer numarası geri kullanılmaz."""
    if plan.durum == PlanDurumu.TAMAMLANDI:
        raise PlanHatasi(f"{plan.sefer_no} tamamlanmış, iptal edilemez.")
    if plan.durum == PlanDurumu.IPTAL:
        raise PlanHatasi(f"{plan.sefer_no} zaten iptal.")
    plan.iptal_aciklamasi = aciklama
    _durum_degistir(db, plan, PlanDurumu.IPTAL, aciklama, kullanici)
    for satir in list(plan.satirlar):
        satir.plan_id = None
        satir.durum = SiparisDurumu.BEKLEMEDE
    db.flush()


def plan_sayaci(db: Session) -> dict[str, int]:
    satirlar = db.execute(
        select(SevkiyatPlani.durum, func.count(SevkiyatPlani.id)).group_by(
            SevkiyatPlani.durum
        )
    ).all()
    return {durum.value: adet for durum, adet in satirlar}


def siparis_sayaci(db: Session) -> dict[str, int]:
    satirlar = db.execute(
        select(SiparisSatiri.durum, func.count(SiparisSatiri.id)).group_by(
            SiparisSatiri.durum
        )
    ).all()
    return {durum.value: adet for durum, adet in satirlar}
