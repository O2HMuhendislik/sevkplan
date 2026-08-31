"""Sevkiyat Planlama — web uygulaması."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    CIKTI_DIZIN,
    DEPO_PROFILLERI,
    ESNETME_GUN_ESIGI,
    RING_DEPO_KODU,
    TUM_DEPOLAR,
)
from app.db import oturum_bagimliligi, semayi_olustur
from app.models import PlanDurumu, SevkiyatPlani, SiparisDurumu, Urun
from app.services import ice_aktarim, plan_servisi, rapor_servisi, sablonlar, yukleme_formu
from app.services.excel import ExcelHatasi
from app.services.plan_servisi import PlanHatasi
from app.services.rapor_servisi import PlanFiltresi

KOK = Path(__file__).resolve().parent


@asynccontextmanager
async def yasam_dongusu(_uygulama: FastAPI) -> AsyncIterator[None]:
    semayi_olustur()
    yield


uygulama = FastAPI(title="Sevkiyat Planlama", lifespan=yasam_dongusu)
uygulama.mount("/static", StaticFiles(directory=KOK / "static"), name="static")
sablon_motoru = Jinja2Templates(directory=str(KOK / "templates"))
sablon_motoru.env.filters["tarih"] = lambda d: d.strftime("%d.%m.%Y") if d else ""
sablon_motoru.env.filters["zaman"] = lambda d: d.strftime("%d.%m.%Y %H:%M") if d else ""


def sayfa(istek: Request, ad: str, **baglam):
    baglam.setdefault("mesaj", istek.query_params.get("mesaj"))
    baglam.setdefault("hata", istek.query_params.get("hata"))
    baglam.setdefault("bugun", date.today())
    baglam.setdefault("ring_depo", RING_DEPO_KODU)
    baglam.setdefault("depolar", DEPO_PROFILLERI)
    baglam.setdefault("esnetme_gun", ESNETME_GUN_ESIGI)
    baglam.setdefault("tum_depolar", TUM_DEPOLAR)
    return sablon_motoru.TemplateResponse(istek, ad, baglam)


def yonlendir(yol: str, mesaj: str | None = None, hata: str | None = None):
    parametreler = {k: v for k, v in (("mesaj", mesaj), ("hata", hata)) if v}
    hedef = f"{yol}?{urlencode(parametreler)}" if parametreler else yol
    return RedirectResponse(hedef, status_code=303)


def plan_getir(db: Session, plan_id: int) -> SevkiyatPlani:
    plan = db.get(SevkiyatPlani, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan bulunamadı")
    return plan


# --------------------------------------------------------------------------- ana ekran
@uygulama.get("/")
def gosterge_paneli(istek: Request, db: Session = Depends(oturum_bagimliligi)):
    return sayfa(
        istek,
        "gosterge.html",
        ozet=rapor_servisi.gosterge_paneli(db),
        son_planlar=rapor_servisi.planlari_getir(db, PlanFiltresi(), limit=10),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db)[:10],
    )


# ------------------------------------------------------------------------- master data
@uygulama.get("/urunler")
def urunler(istek: Request, arama: str = "", db: Session = Depends(oturum_bagimliligi)):
    sorgu = select(Urun).order_by(Urun.urun_grubu, Urun.urun_kodu)
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(Urun.urun_kodu.ilike(desen) | Urun.urun_adi.ilike(desen))
    return sayfa(istek, "urunler.html", urunler=db.scalars(sorgu).all(), arama=arama)


@uygulama.post("/urunler/yeni")
def urun_kaydet(
    urun_kodu: str = Form(...),
    urun_adi: str = Form(...),
    urun_grubu: str = Form(...),
    palet_ici_adet: int = Form(0),
    kamyon_yukleme_adeti: int = Form(0),
    tir_yukleme_adeti: int = Form(0),
    agirlik: str = Form(""),
    header_kod: str = Form(""),
    aktif: bool = Form(True),
    db: Session = Depends(oturum_bagimliligi),
):
    if palet_ici_adet <= 0 and kamyon_yukleme_adeti <= 0 and tir_yukleme_adeti <= 0:
        return yonlendir(
            "/urunler",
            hata="Palet içi adet, kamyon yükleme adeti ve tır yükleme adetinden "
                 "en az biri girilmelidir; yoksa ürün planlanamaz.",
        )
    urun = db.scalar(select(Urun).where(Urun.urun_kodu == urun_kodu.strip()))
    yeni_mi = urun is None
    if urun is None:
        urun = Urun(urun_kodu=urun_kodu.strip())
        db.add(urun)
    urun.urun_adi = urun_adi.strip()
    urun.urun_grubu = urun_grubu.strip().upper() or None
    urun.palet_ici_adet = palet_ici_adet or None
    urun.kamyon_yukleme_adeti = kamyon_yukleme_adeti or None
    urun.tir_yukleme_adeti = tir_yukleme_adeti or None
    urun.agirlik = Decimal(agirlik.replace(",", ".")) if agirlik.strip() else None
    urun.header_kod = header_kod.strip() or None
    urun.aktif = aktif
    db.commit()
    return yonlendir(
        "/urunler", mesaj=f"{urun.urun_kodu} {'eklendi' if yeni_mi else 'güncellendi'}."
    )


@uygulama.post("/urunler/yukle")
async def urunleri_yukle(
    dosya: UploadFile = File(...), db: Session = Depends(oturum_bagimliligi)
):
    try:
        sonuc = ice_aktarim.urunleri_aktar(db, dosya.file, dosya.filename or "urunler.xlsx")
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/urunler", hata=str(hata))
    return yonlendir("/urunler", mesaj=f"Ürün aktarımı: {sonuc.ozet()}")


@uygulama.get("/urunler/sablon")
def urun_sablonu_indir():
    hedef = sablonlar.urun_sablonu(CIKTI_DIZIN / "urun_masterdata_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


# --------------------------------------------------------------------------- siparişler
@uygulama.get("/siparisler")
def siparisler(
    istek: Request,
    durum: str = "BEKLEMEDE",
    arama: str = "",
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "siparisler.html",
        satirlar=rapor_servisi.siparisleri_getir(db, durum or None, arama or None),
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in SiparisDurumu],
    )


@uygulama.post("/siparisler/yukle")
async def siparisleri_yukle(
    dosya: UploadFile = File(...), db: Session = Depends(oturum_bagimliligi)
):
    try:
        sonuc = ice_aktarim.siparisleri_aktar(
            db, dosya.file, dosya.filename or "siparisler.xlsx"
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/siparisler", hata=str(hata))
    uyari = f" — {sonuc.hatali} hatalı kayıt var, HATALI sekmesine bakın." if sonuc.hatali else ""
    return yonlendir("/siparisler", mesaj=f"Sipariş aktarımı: {sonuc.ozet()}{uyari}")


@uygulama.get("/siparisler/sablon")
def siparis_sablonu_indir():
    hedef = sablonlar.siparis_sablonu(CIKTI_DIZIN / "siparis_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


# -------------------------------------------------------------------------------- plan
@uygulama.post("/planlar/uret")
def planlari_uret(
    plan_tarihi: str = Form(""),
    depo_kodu: str = Form(RING_DEPO_KODU),
    kalanlari_zorla: bool = Form(False),
    mix: bool = Form(False),
    db: Session = Depends(oturum_bagimliligi),
):
    tarih = datetime.strptime(plan_tarihi, "%Y-%m-%d").date() if plan_tarihi else date.today()
    try:
        if depo_kodu == TUM_DEPOLAR:
            sonuc = plan_servisi.tum_depolari_planla(
                db, plan_tarihi=tarih, kalanlari_zorla=kalanlari_zorla, mix=mix
            )
        else:
            sonuc = plan_servisi.plan_uret(
                db,
                plan_tarihi=tarih,
                depo_kodu=depo_kodu,
                kalanlari_zorla=kalanlari_zorla,
                mix=mix,
            )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/planlar", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir(
            "/planlar",
            hata=f"Plan üretilemedi. {sonuc.ozet()}",
        )
    return yonlendir("/planlar", mesaj=sonuc.ozet())


@uygulama.post("/planlar/mix")
def mix_plan(
    teslimat_nolar: str = Form(...), db: Session = Depends(oturum_bagimliligi)
):
    secilenler = [p.strip() for p in teslimat_nolar.replace(";", ",").split(",") if p.strip()]
    try:
        plan = plan_servisi.mix_plan_olustur(db, secilenler)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/planlar", hata=str(hata))
    return yonlendir("/planlar", mesaj=f"{plan.sefer_no} mix planı oluşturuldu.")


@uygulama.get("/planlar")
def planlar(
    istek: Request,
    durum: str = "",
    arama: str = "",
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = PlanFiltresi(durum=durum or None, arama=arama or None)
    return sayfa(
        istek,
        "planlar.html",
        planlar=rapor_servisi.planlari_getir(db, filtre),
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in PlanDurumu],
    )


@uygulama.get("/planlar/{plan_id}")
def plan_detay(istek: Request, plan_id: int, db: Session = Depends(oturum_bagimliligi)):
    return sayfa(istek, "plan_detay.html", plan=plan_getir(db, plan_id))


@uygulama.post("/planlar/{plan_id}/axata")
def axata_kaydet(
    plan_id: int, axata_no: str = Form(...), db: Session = Depends(oturum_bagimliligi)
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(db, plan, axata_no)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/planlar/{plan_id}", mesaj=f"Axata no kaydedildi: {plan.axata_no}")


@uygulama.post("/planlar/{plan_id}/mail")
def mail_gonder(plan_id: int, db: Session = Depends(oturum_bagimliligi)):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.mail_gonderildi_isaretle(db, plan)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/planlar/{plan_id}",
        mesaj=(
            "Yükleme formu hazırlandı ve plan 'gönderildi' olarak işaretlendi. "
            "SMTP bağlantısı kurulana kadar formu indirip elle iletin."
        ),
    )


@uygulama.post("/planlar/{plan_id}/tamamla")
def plani_tamamla(plan_id: int, db: Session = Depends(oturum_bagimliligi)):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.plan_tamamla(db, plan)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/planlar/{plan_id}", mesaj=f"{plan.sefer_no} tamamlandı.")


@uygulama.post("/planlar/{plan_id}/iptal")
def plani_iptal(
    plan_id: int, aciklama: str = Form(""), db: Session = Depends(oturum_bagimliligi)
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.plan_iptal(db, plan, aciklama or "Açıklama girilmedi")
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/planlar/{plan_id}",
        mesaj=f"{plan.sefer_no} iptal edildi, siparişler beklemeye alındı.",
    )


@uygulama.get("/planlar/{plan_id}/form")
def yukleme_formu_indir(plan_id: int, db: Session = Depends(oturum_bagimliligi)):
    plan = plan_getir(db, plan_id)
    hedef = yukleme_formu.form_uret(plan)
    return FileResponse(hedef, filename=hedef.name)


# ---------------------------------------------------------------------------- raporlar
@uygulama.get("/raporlar")
def raporlar(istek: Request, db: Session = Depends(oturum_bagimliligi)):
    return sayfa(
        istek,
        "raporlar.html",
        ozet=rapor_servisi.gosterge_paneli(db),
        aylik=rapor_servisi.aylik_ozet(db),
        urun_bazli=rapor_servisi.urun_bazli_ozet(db),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db),
        sevk_durumu=rapor_servisi.sevk_durumu(db),
    )


@uygulama.get("/raporlar/plan-excel")
def plan_excel(durum: str = "", arama: str = "", db: Session = Depends(oturum_bagimliligi)):
    planlar_listesi = rapor_servisi.planlari_getir(
        db, PlanFiltresi(durum=durum or None, arama=arama or None), limit=5000
    )
    hedef = yukleme_formu.plan_listesi_disa_aktar(
        planlar_listesi, CIKTI_DIZIN / "plan_listesi.xlsx"
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/izleme")
def izleme(istek: Request, anahtar: str = "", db: Session = Depends(oturum_bagimliligi)):
    sonuc = rapor_servisi.izleme_sorgusu(db, anahtar) if anahtar.strip() else None
    return sayfa(istek, "izleme.html", anahtar=anahtar, sonuc=sonuc)
