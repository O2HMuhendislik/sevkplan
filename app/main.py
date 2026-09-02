"""Vaillant Group Nakliye Yönetim Sistemi — web uygulaması.

Yapı:
  * `/giris`, `/cikis`, `/sifre-degistir` — kimlik doğrulama
  * `/`                                   — modül seçim ekranı
  * `/ring/...`                           — Ring Planlama modülü
  * `/rota/...`                           — İç Piyasa Sevkiyat Planlama modülü
  * `/urunler`                            — Master Data (modüllerin ortak verisi)
  * `/veri-yonetimi`, `/yonetim/...`      — sistem yönetimi

Her ekran bir modüle bağlıdır ve kullanıcının o modüldeki yetkisine göre açılır.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    CIKTI_DIZIN,
    DEPO_PROFILLERI,
    GRUP_ICI_MIX,
    OTURUM_SURESI_DAKIKA,
    RING_DEPO_KODU,
    TUM_DEPOLAR,
    oturum_anahtari,
)
from app.db import OturumFabrikasi, oturum_bagimliligi, semayi_olustur
from app.guvenlik import PAROLA_KURALLARI, ParolaHatasi
from app.domain.bolgeler import VARSAYILAN_BOLGELER
from app.domain.ic_piyasa import SevkiyatTipi
from app.models import (
    Kullanici,
    Musteri,
    PlanDurumu,
    Rol,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)
from app.moduller import MODULLER
from app.services import (
    ic_piyasa_servisi,
    ic_yukleme_formu,
    ice_aktarim,
    kullanici_servisi,
    plan_servisi,
    rapor_servisi,
    sablonlar,
    temizleme,
    yukleme_formu,
)
from app.services.excel import ExcelHatasi
from app.services.kullanici_servisi import KimlikHatasi, KullaniciHatasi
from app.services.plan_servisi import PlanHatasi
from app.services.rapor_servisi import PlanFiltresi

KOK = Path(__file__).resolve().parent


class YonlendirmeGerekli(Exception):
    """Kimlik doğrulama akışı için yönlendirme (giriş ekranı, parola değiştirme)."""

    def __init__(self, hedef: str) -> None:
        self.hedef = hedef
        super().__init__(hedef)


@asynccontextmanager
async def yasam_dongusu(_uygulama: FastAPI) -> AsyncIterator[None]:
    semayi_olustur()
    with OturumFabrikasi() as db:
        parola = kullanici_servisi.varsayilan_yoneticiyi_olustur(db)
        db.commit()
    if parola:
        print(
            "\n" + "=" * 72,
            "İLK KURULUM — yönetici hesabı oluşturuldu",
            f"  Kullanıcı adı : {kullanici_servisi.VARSAYILAN_YONETICI}",
            f"  Geçici parola : {parola}",
            "  Bu parola yalnızca burada görünür. İlk girişte değiştirmeniz istenecek.",
            "=" * 72 + "\n",
            sep="\n",
        )
    yield


uygulama = FastAPI(
    title="Vaillant Group Nakliye Yönetim Sistemi", lifespan=yasam_dongusu
)
uygulama.add_middleware(
    SessionMiddleware,
    secret_key=oturum_anahtari(),
    max_age=OTURUM_SURESI_DAKIKA * 60,
    same_site="lax",
    session_cookie="sevkplan_oturum",
)
uygulama.mount("/static", StaticFiles(directory=KOK / "static"), name="static")
sablon_motoru = Jinja2Templates(directory=str(KOK / "templates"))
sablon_motoru.env.filters["tarih"] = lambda d: d.strftime("%d.%m.%Y") if d else ""
sablon_motoru.env.filters["zaman"] = lambda d: d.strftime("%d.%m.%Y %H:%M") if d else ""


def _sayi(deger) -> str:
    """Gereksiz ondalıkları atar: 610.000 -> 610, 0.750 -> 0,75."""
    if deger is None:
        return ""
    return format(Decimal(deger).normalize(), "f").replace(".", ",")


sablon_motoru.env.filters["sayi"] = _sayi


# ------------------------------------------------------------------ istisna işleme
@uygulama.exception_handler(YonlendirmeGerekli)
async def _yonlendirme_isle(_istek: Request, hata: YonlendirmeGerekli):
    return RedirectResponse(hata.hedef, status_code=303)


@uygulama.exception_handler(StarletteHTTPException)
async def _http_hatasi_isle(istek: Request, hata: StarletteHTTPException):
    """Yetki ve bulunamadı hatalarını okunur bir sayfa olarak gösterir."""
    if hata.status_code in {403, 404}:
        kullanici_id = istek.session.get("kullanici_id") if "session" in istek.scope else None
        kullanici = None
        if kullanici_id:
            with OturumFabrikasi() as db:
                kullanici = db.get(Kullanici, kullanici_id)
        return sablon_motoru.TemplateResponse(
            istek,
            "hata.html",
            {
                "kod": hata.status_code,
                "mesaj": hata.detail,
                "kullanici": kullanici,
                "moduller": MODULLER,
            },
            status_code=hata.status_code,
        )
    return await http_exception_handler(istek, hata)


# --------------------------------------------------------------------- yardımcılar
def yonlendir(yol: str, mesaj: str | None = None, hata: str | None = None):
    parametreler = {k: v for k, v in (("mesaj", mesaj), ("hata", hata)) if v}
    hedef = f"{yol}?{urlencode(parametreler)}" if parametreler else yol
    return RedirectResponse(hedef, status_code=303)


def oturumdaki_kullanici(
    istek: Request, db: Session = Depends(oturum_bagimliligi)
) -> Kullanici:
    """Giriş yapmış kullanıcıyı döner; yoksa giriş ekranına yönlendirir."""
    kullanici_id = istek.session.get("kullanici_id")
    kullanici = db.get(Kullanici, kullanici_id) if kullanici_id else None
    if kullanici is None or not kullanici.aktif:
        istek.session.clear()
        raise YonlendirmeGerekli("/giris?hata=Oturum+a%C3%A7man%C4%B1z+gerekiyor.")
    if kullanici.parola_degistirmeli and istek.url.path != "/sifre-degistir":
        raise YonlendirmeGerekli("/sifre-degistir")
    return kullanici


def modul_yetkisi(modul_kodu: str, duzenleme: bool = False):
    """Verilen modüle erişimi olan kullanıcıyı döndüren bağımlılık üretir."""

    def kontrol(kullanici: Kullanici = Depends(oturumdaki_kullanici)) -> Kullanici:
        if duzenleme:
            if not kullanici.duzenleyebilir_mi(modul_kodu):
                raise HTTPException(403, "Bu işlem için düzenleme yetkiniz yok.")
        elif not kullanici.gorebilir_mi(modul_kodu):
            raise HTTPException(403, "Bu modüle erişim yetkiniz yok.")
        return kullanici

    return kontrol


def sayfa(istek: Request, ad: str, kullanici: Kullanici | None = None, **baglam):
    baglam.setdefault("mesaj", istek.query_params.get("mesaj"))
    baglam.setdefault("hata", istek.query_params.get("hata"))
    baglam.setdefault("bugun", date.today())
    baglam.setdefault("ring_depo", RING_DEPO_KODU)
    baglam.setdefault("depolar", DEPO_PROFILLERI)
    baglam.setdefault("tum_depolar", TUM_DEPOLAR)
    baglam.setdefault("grup_ici_mix_varsayilan", GRUP_ICI_MIX)
    baglam.setdefault("kullanici", kullanici)
    baglam.setdefault("moduller", MODULLER)
    return sablon_motoru.TemplateResponse(istek, ad, baglam)


def plan_getir(db: Session, plan_id: int) -> SevkiyatPlani:
    plan = db.get(SevkiyatPlani, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan bulunamadı")
    return plan


# ------------------------------------------------------------------ kimlik doğrulama
@uygulama.get("/saglik")
def saglik():
    """İzleme araçları için basit durum ucu."""
    return {"durum": "calisiyor"}


@uygulama.get("/giris")
def giris_ekrani(istek: Request):
    if istek.session.get("kullanici_id"):
        return yonlendir("/")
    return sayfa(istek, "giris.html")


@uygulama.post("/giris")
def giris_yap(
    istek: Request,
    kullanici_adi: str = Form(...),
    parola: str = Form(...),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        kullanici = kullanici_servisi.giris_yap(db, kullanici_adi, parola)
        db.commit()
    except KimlikHatasi as hata:
        db.commit()  # başarısız deneme sayacı yazılsın
        return yonlendir("/giris", hata=str(hata))
    istek.session.clear()
    istek.session["kullanici_id"] = kullanici.id
    return yonlendir("/sifre-degistir" if kullanici.parola_degistirmeli else "/")


@uygulama.get("/cikis")
def cikis(istek: Request):
    istek.session.clear()
    return yonlendir("/giris", mesaj="Oturumunuz kapatıldı.")


@uygulama.get("/sifre-degistir")
def sifre_ekrani(
    istek: Request, kullanici: Kullanici = Depends(oturumdaki_kullanici)
):
    return sayfa(istek, "sifre_degistir.html", kullanici, kurallar=PAROLA_KURALLARI)


@uygulama.post("/sifre-degistir")
def sifre_degistir(
    mevcut_parola: str = Form(...),
    yeni_parola: str = Form(...),
    yeni_parola_tekrar: str = Form(...),
    kullanici: Kullanici = Depends(oturumdaki_kullanici),
    db: Session = Depends(oturum_bagimliligi),
):
    if yeni_parola != yeni_parola_tekrar:
        return yonlendir("/sifre-degistir", hata="Yeni parolalar birbiriyle uyuşmuyor.")
    try:
        kullanici_servisi.parola_degistir(db, kullanici, mevcut_parola, yeni_parola)
        db.commit()
    except (KullaniciHatasi, ParolaHatasi) as hata:
        db.rollback()
        return yonlendir("/sifre-degistir", hata=str(hata))
    return yonlendir("/", mesaj="Parolanız değiştirildi.")


# --------------------------------------------------------------------- modül seçimi
@uygulama.get("/")
def modul_secimi(istek: Request, kullanici: Kullanici = Depends(oturumdaki_kullanici)):
    return sayfa(istek, "modul_secimi.html", kullanici)


# ------------------------------------------------------------ Ring Planlama modülü
@uygulama.get("/ring")
def ring_gosterge(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "gosterge.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db, modul="RING"),
        son_planlar=rapor_servisi.planlari_getir(
            db, PlanFiltresi(modul="RING"), limit=10
        ),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db)[:10],
    )


@uygulama.get("/ring/siparisler")
def siparisler(
    istek: Request,
    durum: str = "BEKLEMEDE",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "siparisler.html",
        kullanici,
        satirlar=rapor_servisi.siparisleri_getir(
            db, durum or None, arama or None, modul="RING"
        ),
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in SiparisDurumu],
    )


@uygulama.post("/ring/siparisler/yukle")
async def siparisleri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.siparisleri_aktar(
            db, dosya.file, dosya.filename or "siparisler.xlsx",
            kullanici.kullanici_adi, modul="RING",
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/ring/siparisler", hata=str(hata))
    uyari = f" — {sonuc.hatali} hatalı kayıt var, HATALI sekmesine bakın." if sonuc.hatali else ""
    return yonlendir("/ring/siparisler", mesaj=f"Sipariş aktarımı: {sonuc.ozet()}{uyari}")


@uygulama.get("/ring/siparisler/sablon")
def siparis_sablonu_indir(kullanici: Kullanici = Depends(modul_yetkisi("RING"))):
    hedef = sablonlar.siparis_sablonu(CIKTI_DIZIN / "siparis_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/ring/planlar/uret")
def planlari_uret(
    plan_tarihi: str = Form(""),
    depo_kodu: str = Form(RING_DEPO_KODU),
    kalanlari_zorla: bool = Form(False),
    grup_ici_mix: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    tarih = datetime.strptime(plan_tarihi, "%Y-%m-%d").date() if plan_tarihi else date.today()
    try:
        ortak = {
            "plan_tarihi": tarih,
            "kullanici": kullanici.kullanici_adi,
            "kalanlari_zorla": kalanlari_zorla,
            "grup_ici_mix": grup_ici_mix,
        }
        if depo_kodu == TUM_DEPOLAR:
            sonuc = plan_servisi.tum_depolari_planla(db, **ortak)
        else:
            sonuc = plan_servisi.plan_uret(db, depo_kodu=depo_kodu, **ortak)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/ring/planlar", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir("/ring/planlar", hata=f"Plan üretilemedi. {sonuc.ozet()}")
    return yonlendir("/ring/planlar", mesaj=sonuc.ozet())


@uygulama.post("/ring/planlar/mix")
def mix_plan(
    teslimat_nolar: str = Form(...),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    secilenler = [p.strip() for p in teslimat_nolar.replace(";", ",").split(",") if p.strip()]
    try:
        plan = plan_servisi.mix_plan_olustur(db, secilenler, kullanici=kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/ring/planlar", hata=str(hata))
    return yonlendir("/ring/planlar", mesaj=f"{plan.sefer_no} mix planı oluşturuldu.")


@uygulama.get("/ring/planlar")
def planlar(
    istek: Request,
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = PlanFiltresi(durum=durum or None, arama=arama or None, modul="RING")
    return sayfa(
        istek,
        "planlar.html",
        kullanici,
        planlar=rapor_servisi.planlari_getir(db, filtre),
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in PlanDurumu],
    )


@uygulama.get("/ring/planlar/{plan_id}")
def plan_detay(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(istek, "plan_detay.html", kullanici, plan=plan_getir(db, plan_id))


@uygulama.post("/ring/planlar/{plan_id}/axata")
def axata_kaydet(
    plan_id: int,
    axata_no: str = Form(...),
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(
            db, plan, axata_no, kullanici.kullanici_adi, aciklama.strip() or None
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ring/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ring/planlar/{plan_id}", mesaj=f"Axata numaraları: {plan.axata_ozeti}"
    )


@uygulama.post("/ring/planlar/{plan_id}/axata/{axata_id}/sil")
def axata_sil(
    plan_id: int,
    axata_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_sil(db, plan, axata_id, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ring/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/ring/planlar/{plan_id}", mesaj="Axata numarası silindi.")


@uygulama.post("/ring/planlar/{plan_id}/mail")
def mail_gonder(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.mail_gonderildi_isaretle(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ring/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ring/planlar/{plan_id}",
        mesaj=(
            "Yükleme formu hazırlandı ve plan 'gönderildi' olarak işaretlendi. "
            "SMTP bağlantısı kurulana kadar formu indirip elle iletin."
        ),
    )


@uygulama.post("/ring/planlar/{plan_id}/tamamla")
def plani_tamamla(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.plan_tamamla(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ring/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/ring/planlar/{plan_id}", mesaj=f"{plan.sefer_no} tamamlandı.")


@uygulama.post("/ring/planlar/{plan_id}/iptal")
def plani_iptal(
    plan_id: int,
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.plan_iptal(
            db, plan, aciklama or "Açıklama girilmedi", kullanici.kullanici_adi
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ring/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ring/planlar/{plan_id}",
        mesaj=f"{plan.sefer_no} iptal edildi, siparişler beklemeye alındı.",
    )


@uygulama.get("/ring/planlar/{plan_id}/form")
def yukleme_formu_indir(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = yukleme_formu.form_uret(plan_getir(db, plan_id))
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/ring/raporlar")
def raporlar(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "raporlar.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db),
        aylik=rapor_servisi.aylik_ozet(db),
        urun_bazli=rapor_servisi.urun_bazli_ozet(db),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db),
        sevk_durumu=rapor_servisi.sevk_durumu(db),
    )


@uygulama.get("/ring/raporlar/plan-excel")
def plan_excel(
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    planlar_listesi = rapor_servisi.planlari_getir(
        db,
        PlanFiltresi(durum=durum or None, arama=arama or None, modul="RING"),
        limit=5000,
    )
    hedef = yukleme_formu.plan_listesi_disa_aktar(
        planlar_listesi, CIKTI_DIZIN / "plan_listesi.xlsx"
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/ring/izleme")
def izleme(
    istek: Request,
    anahtar: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    sonuc = rapor_servisi.izleme_sorgusu(db, anahtar) if anahtar.strip() else None
    return sayfa(istek, "izleme.html", kullanici, anahtar=anahtar, sonuc=sonuc)


# ------------------------------------------- İç Piyasa Sevkiyat Planlama modülü
def _ic_plan_getir(db: Session, plan_id: int) -> SevkiyatPlani:
    """Plan var mı ve gerçekten iç piyasa planı mı? Ring planı bu ekranlarda açılmaz."""
    plan = plan_getir(db, plan_id)
    if not plan.ic_piyasa_mi:
        raise HTTPException(404, "Bu plan iç piyasa modülüne ait değil.")
    return plan


def _tipleri_coz(secilenler: list[str]) -> list[SevkiyatTipi]:
    """Formdan gelen tip seçimini çözer; seçim yoksa üç tip de çalışır."""
    tipler = []
    for deger in secilenler:
        try:
            tipler.append(SevkiyatTipi(deger))
        except ValueError:
            continue
    return tipler or list(SevkiyatTipi)


@uygulama.get("/rota")
def rota_gosterge(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "ic_gosterge.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db, modul="ROTA"),
        tip_ozeti=rapor_servisi.ic_piyasa_ozeti(db),
        bolge_ozeti=rapor_servisi.bolge_ozeti(db)[:12],
        son_planlar=rapor_servisi.planlari_getir(
            db, PlanFiltresi(modul="ROTA"), limit=10
        ),
        musteri_sayisi=db.scalar(select(func.count(Musteri.id))) or 0,
    )


@uygulama.get("/rota/siparisler")
def rota_siparisler(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Beklemedeki siparişlerin müşteri bazında tip önizlemesi.

    Plan üretmeden önce "bu müşteri neden kargoya/rutine düşüyor" sorusunun cevabı
    burada görünür; kural yanlış çalışıyorsa planlamadan önce fark edilir.
    """
    satirlar = list(
        db.scalars(
            select(SiparisSatiri).where(
                SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE,
                SiparisSatiri.plan_id.is_(None),
                SiparisSatiri.modul == "ROTA",
            )
        ).all()
    )
    hatalilar = list(
        db.scalars(
            select(SiparisSatiri)
            .where(
                SiparisSatiri.durum == SiparisDurumu.HATALI,
                SiparisSatiri.modul == "ROTA",
            )
            .order_by(SiparisSatiri.teslimat_no)
            .limit(200)
        ).all()
    )
    return sayfa(
        istek,
        "ic_siparisler.html",
        kullanici,
        musteriler=ic_piyasa_servisi.musteri_ozeti(db, satirlar),
        satir_sayisi=len(satirlar),
        hatalilar=hatalilar,
    )


@uygulama.post("/rota/siparisler/yukle")
async def rota_siparisleri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    """Sipariş dosyasını iç piyasa ekranından yükler.

    İki modül aynı sipariş havuzunu kullanır; dosya Ring ekranından yüklenmiş olsa da
    aynı sonucu verir. Ayrı uç olmasının sebebi yetki: yalnızca ROTA yetkisi olan bir
    kullanıcı Ring ekranını açamaz.
    """
    try:
        sonuc = ice_aktarim.siparisleri_aktar(
            db, dosya.file, dosya.filename or "siparisler.xlsx",
            kullanici.kullanici_adi, modul="ROTA",
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/rota/siparisler", hata=str(hata))
    uyari = (
        f" — {sonuc.hatali} satır alınamadı, aşağıdaki 'Alınamayan satırlar' "
        "tablosuna bakın."
        if sonuc.hatali
        else ""
    )
    return yonlendir(
        "/rota/siparisler", mesaj=f"Sipariş aktarımı: {sonuc.ozet()}{uyari}"
    )


@uygulama.get("/rota/siparisler/sablon")
def rota_siparis_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("ROTA"))):
    hedef = sablonlar.siparis_sablonu(CIKTI_DIZIN / "siparis_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/rota/planlar/uret")
def rota_planlari_uret(
    plan_tarihi: str = Form(""),
    tipler: list[str] = Form([]),
    kalanlari_zorla: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    tarih = (
        datetime.strptime(plan_tarihi, "%Y-%m-%d").date() if plan_tarihi else date.today()
    )
    try:
        sonuc = ic_piyasa_servisi.plan_uret(
            db,
            plan_tarihi=tarih,
            tipler=_tipleri_coz(tipler),
            kullanici=kullanici.kullanici_adi,
            kalanlari_zorla=kalanlari_zorla,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/rota/planlar", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir("/rota/planlar", hata=f"Plan üretilemedi. {sonuc.ozet()}")
    return yonlendir("/rota/planlar", mesaj=sonuc.ozet())


@uygulama.get("/rota/planlar")
def rota_planlar(
    istek: Request,
    durum: str = "",
    tip: str = "",
    bolge: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = PlanFiltresi(
        durum=durum or None,
        arama=arama or None,
        modul="ROTA",
        sevkiyat_tipi=tip or None,
        bolge_kodu=bolge or None,
    )
    return sayfa(
        istek,
        "ic_planlar.html",
        kullanici,
        planlar=rapor_servisi.planlari_getir(db, filtre),
        durum=durum,
        tip=tip,
        bolge=bolge,
        arama=arama,
        durumlar=[d.value for d in PlanDurumu],
    )


@uygulama.get("/rota/planlar/{plan_id}")
def rota_plan_detay(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    return sayfa(
        istek,
        "ic_plan_detay.html",
        kullanici,
        plan=plan,
        duraklar=ic_piyasa_servisi.plan_musterileri(db, plan),
    )


@uygulama.post("/rota/planlar/{plan_id}/axata")
def rota_axata_kaydet(
    plan_id: int,
    axata_no: str = Form(...),
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(
            db, plan, axata_no, kullanici.kullanici_adi, aciklama.strip() or None
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/rota/planlar/{plan_id}", mesaj=f"Axata numaraları: {plan.axata_ozeti}"
    )


@uygulama.post("/rota/planlar/{plan_id}/axata/{axata_id}/sil")
def rota_axata_sil(
    plan_id: int,
    axata_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_sil(db, plan, axata_id, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/rota/planlar/{plan_id}", mesaj="Axata numarası silindi.")


@uygulama.post("/rota/planlar/{plan_id}/arac")
def rota_arac_kaydet(
    plan_id: int,
    nakliyeci: str = Form(""),
    plaka: str = Form(""),
    surucu: str = Form(""),
    surucu_telefon: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        ic_piyasa_servisi.arac_bilgisi_kaydet(
            db, plan, nakliyeci, plaka, surucu, surucu_telefon, kullanici.kullanici_adi
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/rota/planlar/{plan_id}", mesaj="Araç bilgisi kaydedildi.")


@uygulama.post("/rota/planlar/{plan_id}/mail")
def rota_mail_gonder(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.mail_gonderildi_isaretle(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/rota/planlar/{plan_id}",
        mesaj=(
            "Yükleme formu hazırlandı ve plan 'gönderildi' olarak işaretlendi. "
            "SMTP bağlantısı kurulana kadar formu indirip elle iletin."
        ),
    )


@uygulama.post("/rota/planlar/{plan_id}/tamamla")
def rota_plani_tamamla(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.plan_tamamla(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/rota/planlar/{plan_id}", mesaj=f"{plan.sefer_no} tamamlandı.")


@uygulama.post("/rota/planlar/{plan_id}/iptal")
def rota_plani_iptal(
    plan_id: int,
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.plan_iptal(
            db, plan, aciklama or "Açıklama girilmedi", kullanici.kullanici_adi
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/rota/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/rota/planlar/{plan_id}",
        mesaj=f"{plan.sefer_no} iptal edildi, siparişler beklemeye alındı.",
    )


@uygulama.get("/rota/planlar/{plan_id}/form")
def rota_form_indir(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = ic_yukleme_formu.form_uret(_ic_plan_getir(db, plan_id))
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/rota/gunluk-form")
def rota_gunluk_form(
    tarih: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Bir günün bütün iç piyasa planları tek kitapta, sevkiyat tipine göre sayfalanmış."""
    gun = datetime.strptime(tarih, "%Y-%m-%d").date() if tarih else date.today()
    planlar_listesi = rapor_servisi.planlari_getir(
        db, PlanFiltresi(modul="ROTA", baslangic=gun, bitis=gun), limit=500
    )
    if not planlar_listesi:
        return yonlendir(
            "/rota/planlar", hata=f"{gun:%d.%m.%Y} için iç piyasa planı bulunamadı."
        )
    hedef = ic_yukleme_formu.gunluk_form(planlar_listesi)
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/rota/raporlar")
def rota_raporlar(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "ic_raporlar.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db, modul="ROTA"),
        tip_ozeti=rapor_servisi.ic_piyasa_ozeti(db),
        bolge_ozeti=rapor_servisi.bolge_ozeti(db),
    )


@uygulama.get("/rota/raporlar/plan-excel")
def rota_plan_excel(
    durum: str = "",
    tip: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    planlar_listesi = rapor_servisi.planlari_getir(
        db,
        PlanFiltresi(
            durum=durum or None,
            arama=arama or None,
            modul="ROTA",
            sevkiyat_tipi=tip or None,
        ),
        limit=5000,
    )
    hedef = ic_yukleme_formu.plan_listesi_disa_aktar(
        planlar_listesi, CIKTI_DIZIN / "ic_piyasa_planlari.xlsx"
    )
    return FileResponse(hedef, filename=hedef.name)


# -------------------------------------------------------- iç piyasa müşteri master data
@uygulama.get("/rota/musteriler")
def rota_musteriler(
    istek: Request,
    arama: str = "",
    tir: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "musteriler.html",
        kullanici,
        musteriler=rapor_servisi.musterileri_getir(db, arama or None, tir or None),
        arama=arama,
        tir=tir,
        toplam=db.scalar(select(func.count(Musteri.id))) or 0,
        bolgeler=VARSAYILAN_BOLGELER,
    )


@uygulama.post("/rota/musteriler/yukle")
async def rota_musterileri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.musterileri_aktar(
            db, dosya.file, dosya.filename or "musteriler.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/rota/musteriler", hata=str(hata))
    return yonlendir("/rota/musteriler", mesaj=f"Müşteri aktarımı: {sonuc.ozet()}")


@uygulama.get("/rota/musteriler/sablon")
def rota_musteri_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("ROTA"))):
    hedef = sablonlar.musteri_sablonu(CIKTI_DIZIN / "musteri_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/rota/musteriler/{musteri_id}")
def rota_musteri_guncelle(
    musteri_id: int,
    tir_girisi: str = Form("?"),
    bolge_kodu: str = Form(""),
    il: str = Form(""),
    ilce: str = Form(""),
    notlar: str = Form(""),
    aktif: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.domain.iller import yer_adi

    musteri = db.get(Musteri, musteri_id)
    if musteri is None:
        raise HTTPException(404, "Müşteri bulunamadı")
    musteri.tir_girisi = tir_girisi if tir_girisi in {"E", "H"} else "?"
    musteri.bolge_kodu = bolge_kodu.strip() or None
    musteri.il = yer_adi(il) or musteri.il
    musteri.ilce = yer_adi(ilce) or None
    musteri.notlar = notlar.strip() or None
    musteri.aktif = aktif
    db.commit()
    return yonlendir(
        "/rota/musteriler", mesaj=f"{musteri.bayi_adi} güncellendi."
    )


# --------------------------------------------------------------- Raporlama modülü
@uygulama.get("/raporlama")
def raporlama_ozet(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("RAPORLAMA")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Modüller arası özet ve plana alınma süresi KPI'ı."""
    return sayfa(
        istek,
        "raporlama_ozet.html",
        kullanici,
        modul_ozeti=rapor_servisi.modul_ozeti(db),
        kpiler=rapor_servisi.planlama_kpi(db),
    )


@uygulama.get("/raporlama/siparisler")
def raporlama_siparisler(
    istek: Request,
    modul: str = "",
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RAPORLAMA")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Bütün modüllerin siparişleri; modül, durum ve serbest metinle filtrelenir."""
    return sayfa(
        istek,
        "raporlama_siparisler.html",
        kullanici,
        satirlar=rapor_servisi.tum_siparisler(
            db, modul or None, durum or None, arama or None
        ),
        modul=modul,
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in SiparisDurumu],
        modul_adlari=rapor_servisi.MODUL_ADLARI,
    )


@uygulama.get("/raporlama/planlar")
def raporlama_planlar(
    istek: Request,
    modul: str = "",
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RAPORLAMA")),
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = PlanFiltresi(
        durum=durum or None, arama=arama or None, modul=modul or None
    )
    return sayfa(
        istek,
        "raporlama_planlar.html",
        kullanici,
        planlar=rapor_servisi.planlari_getir(db, filtre),
        modul=modul,
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in PlanDurumu],
        modul_adlari=rapor_servisi.MODUL_ADLARI,
    )


# ---------------------------------------------------------------------- master data
@uygulama.get("/urunler")
def urunler(
    istek: Request,
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA")),
    db: Session = Depends(oturum_bagimliligi),
):
    sorgu = select(Urun).order_by(Urun.urun_grubu, Urun.urun_kodu)
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(Urun.urun_kodu.ilike(desen) | Urun.urun_adi.ilike(desen))
    return sayfa(
        istek, "urunler.html", kullanici, urunler=db.scalars(sorgu).all(), arama=arama
    )


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
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
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
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.urunleri_aktar(
            db, dosya.file, dosya.filename or "urunler.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/urunler", hata=str(hata))
    return yonlendir("/urunler", mesaj=f"Ürün aktarımı: {sonuc.ozet()}")


@uygulama.get("/urunler/sablon")
def urun_sablonu_indir(kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA"))):
    hedef = sablonlar.urun_sablonu(CIKTI_DIZIN / "urun_masterdata_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


# ------------------------------------------------------------------- veri yönetimi
@uygulama.get("/veri-yonetimi")
def veri_yonetimi(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(istek, "veri_yonetimi.html", kullanici, sayimlar=temizleme.sayimlar(db))


@uygulama.post("/veri-yonetimi/sil")
def veri_sil(
    islem: str = Form(...),
    baslangic: str = Form(""),
    bitis: str = Form(""),
    tamamlananlar_dahil: bool = Form(False),
    siparisleri_de_sil: bool = Form(False),
    sayaci_sifirla: bool = Form(False),
    onay: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    if onay.strip().upper() != "SIL":
        return yonlendir(
            "/veri-yonetimi",
            hata="Silme işlemi için onay kutusuna büyük harfle SIL yazmalısınız.",
        )

    def tarihe_cevir(deger: str):
        return datetime.strptime(deger, "%Y-%m-%d").date() if deger else None

    if islem == "bekleyen":
        sonuc = temizleme.bekleyen_siparisleri_sil(db)
    elif islem == "planlar":
        sonuc = temizleme.planlari_sil(
            db,
            baslangic=tarihe_cevir(baslangic),
            bitis=tarihe_cevir(bitis),
            tamamlananlar_dahil=tamamlananlar_dahil,
            siparisleri_de_sil=siparisleri_de_sil,
        )
    elif islem == "siparis_ve_planlar":
        sonuc = temizleme.siparis_ve_planlari_sil(db, sayaci_sifirla=sayaci_sifirla)
    elif islem == "hepsi":
        sonuc = temizleme.her_seyi_sil(db)
    else:
        return yonlendir("/veri-yonetimi", hata=f"Bilinmeyen işlem: {islem}")

    db.commit()
    return yonlendir("/veri-yonetimi", mesaj=sonuc.ozet())


# --------------------------------------------------------------- kullanıcı yönetimi
@uygulama.get("/yonetim/kullanicilar")
def kullanicilar(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "kullanicilar.html",
        kullanici,
        kullanicilar=kullanici_servisi.kullanicilari_getir(db),
        roller=[r.value for r in Rol],
        kurallar=PAROLA_KURALLARI,
    )


@uygulama.post("/yonetim/kullanicilar/yeni")
def kullanici_ekle(
    kullanici_adi: str = Form(...),
    ad_soyad: str = Form(...),
    rol: str = Form(...),
    eposta: str = Form(""),
    firma: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        yeni, parola = kullanici_servisi.kullanici_olustur(
            db, kullanici_adi, ad_soyad, Rol(rol), eposta, firma
        )
        db.commit()
    except (KullaniciHatasi, ParolaHatasi, ValueError) as hata:
        db.rollback()
        return yonlendir("/yonetim/kullanicilar", hata=str(hata))
    return yonlendir(
        "/yonetim/kullanicilar",
        mesaj=(
            f"{yeni.kullanici_adi} oluşturuldu. Geçici parola: {parola} — "
            "bu parola bir daha gösterilmeyecek, kullanıcıya iletin."
        ),
    )


@uygulama.post("/yonetim/kullanicilar/{kullanici_id}/guncelle")
def kullanici_guncelle(
    kullanici_id: int,
    ad_soyad: str = Form(...),
    rol: str = Form(...),
    eposta: str = Form(""),
    firma: str = Form(""),
    aktif: bool = Form(False),
    kilidi_ac: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = db.get(Kullanici, kullanici_id)
    if hedef is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    yeni_rol = Rol(rol)
    son_yonetici = (
        hedef.rol is Rol.YONETICI
        and hedef.aktif
        and kullanici_servisi.yonetici_sayisi(db) == 1
    )
    if son_yonetici and (yeni_rol is not Rol.YONETICI or not aktif):
        return yonlendir(
            "/yonetim/kullanicilar",
            hata="Sistemde en az bir aktif yönetici kalmalı.",
        )
    hedef.ad_soyad = ad_soyad.strip()
    hedef.rol = yeni_rol
    hedef.eposta = eposta.strip() or None
    hedef.firma = firma.strip() or None
    hedef.aktif = aktif
    if kilidi_ac:
        hedef.kilitli_mi = False
        hedef.basarisiz_deneme = 0
    db.commit()
    return yonlendir("/yonetim/kullanicilar", mesaj=f"{hedef.kullanici_adi} güncellendi.")


@uygulama.post("/yonetim/kullanicilar/{kullanici_id}/yetkiler")
async def yetkileri_kaydet(
    istek: Request,
    kullanici_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = db.get(Kullanici, kullanici_id)
    if hedef is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    form = await istek.form()
    secimler = {
        anahtar.removeprefix("modul_"): deger
        for anahtar, deger in form.items()
        if anahtar.startswith("modul_") and deger in {"GORUNTULE", "DUZENLE"}
    }
    try:
        kullanici_servisi.yetkileri_ayarla(db, hedef, secimler)
        db.commit()
    except KullaniciHatasi as hata:
        db.rollback()
        return yonlendir("/yonetim/kullanicilar", hata=str(hata))
    return yonlendir(
        "/yonetim/kullanicilar", mesaj=f"{hedef.kullanici_adi} yetkileri güncellendi."
    )


@uygulama.post("/yonetim/kullanicilar/{kullanici_id}/parola-sifirla")
def parola_sifirla(
    kullanici_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = db.get(Kullanici, kullanici_id)
    if hedef is None:
        raise HTTPException(404, "Kullanıcı bulunamadı")
    parola = kullanici_servisi.parola_sifirla(db, hedef)
    db.commit()
    return yonlendir(
        "/yonetim/kullanicilar",
        mesaj=(
            f"{hedef.kullanici_adi} için geçici parola: {parola} — "
            "kullanıcı ilk girişte değiştirecek."
        ),
    )
