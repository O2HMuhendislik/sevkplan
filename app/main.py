"""Vaillant Group Nakliye Yönetim Sistemi — web uygulaması.

Yapı:
  * `/giris`, `/cikis`, `/sifre-degistir` — kimlik doğrulama
  * `/`                                   — modül seçim ekranı
  * `/ring/...`                           — Ring Planlama modülü
  * `/rota/...`                           — İç Piyasa Sevkiyat Planlama modülü
  * `/ihracat/...`                        — İhracat Planlama modülü
  * `/raporlama/...`                      — Modüller arası raporlama ve KPI
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
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
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
    depo_profili,
    oturum_anahtari,
)
from app.db import OturumFabrikasi, oturum_bagimliligi, semayi_olustur
from app.guvenlik import PAROLA_KURALLARI, ParolaHatasi
from app.domain.bolgeler import VARSAYILAN_BOLGELER
from app.domain.ic_piyasa import SevkiyatTipi
from app.models import (
    IhracatMusterisi,
    IhracatUrunu,
    Kullanici,
    Musteri,
    PlanDurumu,
    Rol,
    SevkiyatPlani,
    SiparisDurumu,
    SiparisSatiri,
    Urun,
)
from app.moduller import MODUL_HARITASI, MODULLER
from app.services import (
    gomulu_veri,
    ic_piyasa_servisi,
    ic_yukleme_formu,
    ice_aktarim,
    ihracat_servisi,
    ihracat_yukleme_formu,
    istif_servisi,
    kullanici_servisi,
    marka,
    masterdata_servisi,
    musteri_ek_bilgi,
    plan_raporu,
    plan_servisi,
    rapor_servisi,
    sablonlar,
    temizleme,
    urun_bagi_servisi,
    veri_formatlari,
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
        # Programla gelen master data yalnızca ilgili tablo boşsa yüklenir.
        yuklenenler = gomulu_veri.eksikleri_yukle(db)
        db.commit()
    for satir in yuklenenler:
        print(f"Gömülü master data — {satir}")
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
    # Başlık çubuğu hangi modülde olunduğunu simge ve renkle gösteriyor.
    baglam.setdefault("modul_haritasi", MODUL_HARITASI)
    # Logo değişince tarayıcı eskisini önbellekten sunmasın.
    baglam.setdefault("logo_surumu", marka.surum())
    return sablon_motoru.TemplateResponse(istek, ad, baglam)


EKRAN_LIMITI = 500
"""Master Data listelerinde ekranda gösterilen en fazla kayıt; indirme sınırsızdır."""

MD_YETKI = modul_yetkisi("MASTERDATA")
MD_DUZENLEME = modul_yetkisi("MASTERDATA", duzenleme=True)


def _sorgu_metni(**alanlar: str) -> str:
    """Filtreyi indirme bağlantısına taşır: ekranda görülen liste = inen dosya."""
    return urlencode({ad: deger for ad, deger in alanlar.items() if deger})


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
        bekleyenler=rapor_servisi.bekleyen_ozeti(db, modul="RING")[:10],
        hatalilar=rapor_servisi.hatali_ozeti(db, modul="RING")[:5],
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
    plan = plan_getir(db, plan_id)
    return sayfa(
        istek,
        "plan_detay.html",
        kullanici,
        plan=plan,
        bag_uyarilari=urun_bagi_servisi.plan_uyarilari(db, plan),
    )


@uygulama.post("/ring/planlar/{plan_id}/axata")
def axata_kaydet(
    plan_id: int,
    axata_no: str = Form(...),
    aciklama: str = Form(""),
    depo_kodu: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(
            db,
            plan,
            axata_no,
            kullanici.kullanici_adi,
            aciklama.strip() or None,
            depo_kodu=depo_kodu.strip() or None,
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


@uygulama.get("/ring/gunluk-form")
def ring_gunluk_form(
    tarih: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Bir günün bütün ring planları tek kitapta."""
    gun = datetime.strptime(tarih, "%Y-%m-%d").date() if tarih else date.today()
    planlar_listesi = rapor_servisi.planlari_getir(
        db, PlanFiltresi(modul="RING", baslangic=gun, bitis=gun), limit=500
    )
    if not planlar_listesi:
        return yonlendir(
            "/ring/planlar", hata=f"{gun:%d.%m.%Y} için ring planı bulunamadı."
        )
    hedef = yukleme_formu.gunluk_form(planlar_listesi)
    return FileResponse(hedef, filename=hedef.name)


BEKLEYEN_MODULLERI = {
    "RING": "/ring/bekleyenler",
    "ROTA": "/rota/bekleyenler",
    "IHRACAT": "/ihracat/bekleyenler",
}


def _bekleyen_sayfasi(
    istek: Request, kullanici: Kullanici, db: Session, modul: str,
    durum: str, arama: str,
):
    """Plana giremeyen sipariş satırlarının detay ekranı (üç modülde de aynı)."""
    satirlar = rapor_servisi.bekleyen_detaylari(db, modul=modul)
    if durum:
        satirlar = [s for s in satirlar if s.durum.value == durum]
    if arama:
        desen = arama.strip().lower()
        satirlar = [
            s for s in satirlar
            if desen in " ".join(
                str(deger or "").lower()
                for deger in (
                    s.bayi_adi, s.alici_firma, s.sehir, s.ilce, s.urun_kodu,
                    s.urun_adi, s.teslimat_no, s.siparis_no, s.depo_kodu,
                )
            )
        ]
    return sayfa(
        istek,
        "bekleyenler.html",
        kullanici,
        satirlar=satirlar,
        durum=durum,
        arama=arama,
        modul_kodu=modul,
        excel_yolu=f"{BEKLEYEN_MODULLERI[modul]}/excel",
    )


@uygulama.get("/ring/bekleyenler")
def ring_bekleyenler(
    istek: Request, durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_sayfasi(istek, kullanici, db, "RING", durum, arama)


@uygulama.get("/rota/bekleyenler")
def rota_bekleyenler(
    istek: Request, durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_sayfasi(istek, kullanici, db, "ROTA", durum, arama)


@uygulama.get("/ihracat/bekleyenler")
def ihracat_bekleyenler(
    istek: Request, durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_sayfasi(istek, kullanici, db, "IHRACAT", durum, arama)


def _bekleyen_excel(db: Session, modul: str, durum: str, arama: str):
    satirlar = rapor_servisi.bekleyen_detaylari(db, modul=modul)
    if durum:
        satirlar = [s for s in satirlar if s.durum.value == durum]
    hedef = plan_raporu.bekleyen_raporu(
        satirlar, CIKTI_DIZIN / f"bekleyen_siparisler_{modul.lower()}.xlsx", modul
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/ring/bekleyenler/excel")
def ring_bekleyen_excel(
    durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_excel(db, "RING", durum, arama)


@uygulama.get("/rota/bekleyenler/excel")
def rota_bekleyen_excel(
    durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_excel(db, "ROTA", durum, arama)


@uygulama.get("/ihracat/bekleyenler/excel")
def ihracat_bekleyen_excel(
    durum: str = "", arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _bekleyen_excel(db, "IHRACAT", durum, arama)


@uygulama.post("/plan/{plan_id}/yukleme-notu")
def yukleme_notu_kaydet(
    plan_id: int,
    yukleme_notu: str = Form(""),
    kullanici: Kullanici = Depends(oturumdaki_kullanici),
    db: Session = Depends(oturum_bagimliligi),
):
    """Yükleme formuna basılacak serbest notu kaydeder (üç modül için de aynı)."""
    plan = db.get(SevkiyatPlani, plan_id)
    if plan is None:
        raise HTTPException(404, "Plan bulunamadı")
    if not kullanici.duzenleyebilir_mi(plan.modul or "RING"):
        raise HTTPException(403, "Bu işlem için düzenleme yetkiniz yok.")
    plan.yukleme_notu = (yukleme_notu or "").strip() or None
    db.commit()
    return yonlendir(
        f"{plan.modul_yolu}/{plan.id}", mesaj="Yükleme notu kaydedildi."
    )


@uygulama.get("/marka/logo")
def marka_logosu():
    """Başlıktaki logo. Yüklenmemişse depodaki yer tutucu döner.

    Giriş ekranında da gösterildiği için oturum aranmaz.
    """
    yol = marka.logo_yolu()
    return FileResponse(yol, media_type=marka.icerik_turu(yol))


@uygulama.post("/yonetim/logo")
async def marka_logosu_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True)),
):
    try:
        marka.logo_kaydet(await dosya.read(), dosya.filename or "")
    except marka.LogoHatasi as hata:
        return yonlendir("/veri-yonetimi", hata=str(hata))
    return yonlendir("/veri-yonetimi", mesaj="Logo güncellendi.")


@uygulama.post("/yonetim/logo/sil")
def marka_logosu_sil(kullanici: Kullanici = Depends(modul_yetkisi("YONETIM", duzenleme=True))):
    if not marka.logo_sil():
        return yonlendir("/veri-yonetimi", hata="Yüklenmiş logo yok.")
    return yonlendir("/veri-yonetimi", mesaj="Logo kaldırıldı, yer tutucuya dönüldü.")


@uygulama.get("/rapor/plan-raporu")
def plan_raporu_indir(
    modul: str = "",
    durum: str = "",
    baslangic: str = "",
    bitis: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(oturumdaki_kullanici),
    db: Session = Depends(oturum_bagimliligi),
):
    """Özet + ürün grubu + plan listesi + sevk durumu raporu (bütün modüller için aynı).

    `modul` verilmezse kullanıcının yetkili olduğu bütün modüller tek kitapta gelir.
    """
    izinliler = [
        kod for kod in plan_raporu.MODUL_ADLARI if kullanici.gorebilir_mi(kod)
    ]
    if modul and modul not in izinliler:
        raise HTTPException(403, "Bu modülün raporunu görme yetkiniz yok")

    def gune_cevir(deger: str):
        return datetime.strptime(deger, "%Y-%m-%d").date() if deger else None

    filtre = PlanFiltresi(
        durum=durum or None,
        baslangic=gune_cevir(baslangic),
        bitis=gune_cevir(bitis),
        arama=arama or None,
        modul=modul or None,
    )
    planlar_listesi = rapor_servisi.planlari_getir(db, filtre, limit=5000)
    if not modul:
        planlar_listesi = [p for p in planlar_listesi if p.modul in izinliler]
    hedef = plan_raporu.rapor_uret(
        planlar_listesi,
        CIKTI_DIZIN / f"plan_raporu_{modul.lower() or 'tum'}.xlsx",
        modul=modul or None,
    )
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
        ozet=rapor_servisi.gosterge_paneli(db, modul="RING"),
        aylik=rapor_servisi.aylik_ozet(db, modul="RING"),
        urun_bazli=rapor_servisi.urun_bazli_ozet(db, modul="RING"),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db, modul="RING"),
        hatalilar=rapor_servisi.hatali_ozeti(db, modul="RING"),
        profil=depo_profili(RING_DEPO_KODU),
        sevk_durumu=rapor_servisi.sevk_durumu(db, modul="RING"),
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
def ring_izleme_yonlendir(anahtar: str = ""):
    """Eski adres. Sorgu bütün modüllerde arama yaptığı için ekran Raporlama'ya taşındı;
    tarayıcı sık kullanılanlarında kalan bağlantılar kırılmasın diye yönlendiriyoruz."""
    ek = f"?{urlencode({'anahtar': anahtar})}" if anahtar.strip() else ""
    return RedirectResponse(f"/raporlama/izleme{ek}", status_code=307)


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
        arac_ozeti=rapor_servisi.ic_arac_ozeti(db),
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
            # Sınırlar Master Data > Sistem Tanımları ekranından gelir; kayıt yoksa
            # koddaki varsayılanlar geçerlidir.
            kurallar=masterdata_servisi.kurallari_kur(db),
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
    arac: str = "",
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
        arac_tipi=arac or None,
    )
    return sayfa(
        istek,
        "ic_planlar.html",
        kullanici,
        planlar=rapor_servisi.planlari_getir(db, filtre),
        durum=durum,
        tip=tip,
        bolge=bolge,
        arac=arac,
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
        bag_uyarilari=urun_bagi_servisi.plan_uyarilari(db, plan),
    )


@uygulama.post("/rota/planlar/{plan_id}/axata")
def rota_axata_kaydet(
    plan_id: int,
    axata_no: str = Form(...),
    aciklama: str = Form(""),
    depo_kodu: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ic_plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(
            db,
            plan,
            axata_no,
            kullanici.kullanici_adi,
            aciklama.strip() or None,
            depo_kodu=depo_kodu.strip() or None,
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
        arac_ozeti=rapor_servisi.ic_arac_ozeti(db),
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
@uygulama.get("/masterdata/musteriler")
def rota_musteriler(
    istek: Request,
    arama: str = "",
    tir: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "musteriler.html",
        kullanici,
        musteriler=rapor_servisi.musterileri_getir(db, arama or None, tir or None),
        arama=arama,
        tir=tir,
        sorgu=_sorgu_metni(arama=arama, tir=tir),
        toplam=db.scalar(select(func.count(Musteri.id))) or 0,
        bolgeler=VARSAYILAN_BOLGELER,
    )


@uygulama.post("/masterdata/musteriler/yukle")
async def rota_musterileri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.musterileri_aktar(
            db, dosya.file, dosya.filename or "musteriler.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/musteriler", hata=str(hata))
    return yonlendir("/masterdata/musteriler", mesaj=f"Müşteri aktarımı: {sonuc.ozet()}")


@uygulama.get("/masterdata/musteriler/sablon")
def rota_musteri_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA"))):
    hedef = sablonlar.musteri_sablonu(CIKTI_DIZIN / "musteri_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/masterdata/musteriler/{musteri_id:int}")
def rota_musteri_guncelle(
    musteri_id: int,
    tir_girisi: str = Form("?"),
    bolge_kodu: str = Form(""),
    il: str = Form(""),
    ilce: str = Form(""),
    notlar: str = Form(""),
    aktif: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
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
        "/masterdata/musteriler", mesaj=f"{musteri.bayi_adi} güncellendi."
    )


# ------------------------------------------------------------- İhracat Planlama modülü
def _ihracat_plan_getir(db: Session, plan_id: int) -> SevkiyatPlani:
    plan = plan_getir(db, plan_id)
    if not plan.ihracat_mi:
        raise HTTPException(404, "Bu plan ihracat modülüne ait değil.")
    return plan


def _ihracat_bekleyen_satirlar(db: Session) -> list[SiparisSatiri]:
    return list(
        db.scalars(
            select(SiparisSatiri).where(
                SiparisSatiri.durum == SiparisDurumu.BEKLEMEDE,
                SiparisSatiri.plan_id.is_(None),
                SiparisSatiri.modul == "IHRACAT",
            )
        ).all()
    )


@uygulama.get("/ihracat")
def ihracat_gosterge(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "ihracat_gosterge.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db, modul="IHRACAT"),
        ulke_ozeti=rapor_servisi.ihracat_ulke_ozeti(db),
        son_planlar=rapor_servisi.planlari_getir(
            db, PlanFiltresi(modul="IHRACAT"), limit=10
        ),
        musteri_sayisi=db.scalar(select(func.count(IhracatMusterisi.id))) or 0,
        bekleyen_satir=len(_ihracat_bekleyen_satirlar(db)),
    )


@uygulama.get("/ihracat/siparisler")
def ihracat_siparisler(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Beklemedeki ihracat siparişlerinin müşteri bazında araç önizlemesi."""
    satirlar = _ihracat_bekleyen_satirlar(db)
    hatalilar = list(
        db.scalars(
            select(SiparisSatiri)
            .where(
                SiparisSatiri.durum == SiparisDurumu.HATALI,
                SiparisSatiri.modul == "IHRACAT",
            )
            .limit(200)
        ).all()
    )
    return sayfa(
        istek,
        "ihracat_siparisler.html",
        kullanici,
        musteriler=ihracat_servisi.musteri_onizlemesi(db, satirlar),
        satir_sayisi=len(satirlar),
        hatalilar=hatalilar,
    )


@uygulama.post("/ihracat/siparisler/yukle")
async def ihracat_siparisleri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.ihracat_siparislerini_aktar(
            db, dosya.file, dosya.filename or "ihracat.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/ihracat/siparisler", hata=str(hata))
    return yonlendir("/ihracat/siparisler", mesaj=f"Sipariş aktarımı: {sonuc.ozet()}")


@uygulama.get("/ihracat/siparisler/sablon")
def ihracat_siparis_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT"))):
    hedef = sablonlar.ihracat_siparis_sablonu(CIKTI_DIZIN / "ihracat_siparis_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/ihracat/planlar/uret")
def ihracat_planlari_uret(
    plan_tarihi: str = Form(""),
    kalanlari_zorla: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    tarih = (
        datetime.strptime(plan_tarihi, "%Y-%m-%d").date() if plan_tarihi else date.today()
    )
    try:
        sonuc = ihracat_servisi.plan_uret(
            db,
            plan_tarihi=tarih,
            kullanici=kullanici.kullanici_adi,
            kalanlari_zorla=kalanlari_zorla,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/ihracat/planlar", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir("/ihracat/planlar", hata=f"Plan üretilemedi. {sonuc.ozet()}")
    return yonlendir("/ihracat/planlar", mesaj=sonuc.ozet())


@uygulama.get("/ihracat/planlar")
def ihracat_planlar(
    istek: Request,
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = PlanFiltresi(durum=durum or None, arama=arama or None, modul="IHRACAT")
    return sayfa(
        istek,
        "ihracat_planlar.html",
        kullanici,
        planlar=rapor_servisi.planlari_getir(db, filtre),
        durum=durum,
        arama=arama,
        durumlar=[d.value for d in PlanDurumu],
    )


@uygulama.get("/ihracat/planlar/{plan_id}")
def ihracat_plan_detay(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    return sayfa(
        istek,
        "ihracat_plan_detay.html",
        kullanici,
        plan=plan,
        bag_uyarilari=urun_bagi_servisi.plan_uyarilari(db, plan),
    )


@uygulama.post("/ihracat/planlar/{plan_id}/axata")
def ihracat_axata_kaydet(
    plan_id: int,
    axata_no: str = Form(...),
    aciklama: str = Form(""),
    depo_kodu: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_gir(
            db,
            plan,
            axata_no,
            kullanici.kullanici_adi,
            aciklama.strip() or None,
            depo_kodu=depo_kodu.strip() or None,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ihracat/planlar/{plan_id}", mesaj=f"Axata numaraları: {plan.axata_ozeti}"
    )


@uygulama.post("/ihracat/planlar/{plan_id}/axata/{axata_id}/sil")
def ihracat_axata_sil(
    plan_id: int,
    axata_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        plan_servisi.axata_no_sil(db, plan, axata_id, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/ihracat/planlar/{plan_id}", mesaj="Axata numarası silindi.")


@uygulama.post("/ihracat/planlar/{plan_id}/arac")
def ihracat_arac_kaydet(
    plan_id: int,
    nakliyeci: str = Form(""),
    plaka: str = Form(""),
    konteyner_no: str = Form(""),
    muhur_no: str = Form(""),
    surucu: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        ihracat_servisi.arac_bilgisi_kaydet(
            db, plan, nakliyeci, plaka, konteyner_no, muhur_no, surucu,
            kullanici.kullanici_adi,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/ihracat/planlar/{plan_id}", mesaj="Araç bilgisi kaydedildi.")


@uygulama.post("/ihracat/planlar/{plan_id}/mail")
def ihracat_mail_gonder(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        plan_servisi.mail_gonderildi_isaretle(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ihracat/planlar/{plan_id}",
        mesaj="Yükleme formu hazırlandı ve plan 'gönderildi' olarak işaretlendi.",
    )


@uygulama.post("/ihracat/planlar/{plan_id}/tamamla")
def ihracat_plani_tamamla(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        plan_servisi.plan_tamamla(db, plan, kullanici.kullanici_adi)
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(f"/ihracat/planlar/{plan_id}", mesaj=f"{plan.sefer_no} tamamlandı.")


@uygulama.post("/ihracat/planlar/{plan_id}/iptal")
def ihracat_plani_iptal(
    plan_id: int,
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    plan = _ihracat_plan_getir(db, plan_id)
    try:
        plan_servisi.plan_iptal(
            db, plan, aciklama or "Açıklama girilmedi", kullanici.kullanici_adi
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir(f"/ihracat/planlar/{plan_id}", hata=str(hata))
    return yonlendir(
        f"/ihracat/planlar/{plan_id}",
        mesaj=f"{plan.sefer_no} iptal edildi, siparişler beklemeye alındı.",
    )


@uygulama.get("/ihracat/planlar/{plan_id}/form")
def ihracat_form_indir(
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = ihracat_yukleme_formu.form_uret(_ihracat_plan_getir(db, plan_id))
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/ihracat/gunluk-form")
def ihracat_gunluk_form(
    tarih: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    gun = datetime.strptime(tarih, "%Y-%m-%d").date() if tarih else date.today()
    planlar_listesi = rapor_servisi.planlari_getir(
        db, PlanFiltresi(modul="IHRACAT", baslangic=gun, bitis=gun), limit=500
    )
    if not planlar_listesi:
        return yonlendir(
            "/ihracat/planlar", hata=f"{gun:%d.%m.%Y} için ihracat planı bulunamadı."
        )
    hedef = ihracat_yukleme_formu.gunluk_form(planlar_listesi)
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/ihracat/plan-excel", include_in_schema=False)
def ihracat_plan_excel_yonlendir(durum: str = "", arama: str = ""):
    """Eski adres: liste artık diğer modüllerdeki gibi /ihracat/raporlar altında."""
    ek = urlencode({"durum": durum, "arama": arama})
    return RedirectResponse(f"/ihracat/raporlar/plan-excel?{ek}", status_code=307)


@uygulama.get("/ihracat/raporlar")
def ihracat_raporlar(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "ihracat_raporlar.html",
        kullanici,
        ozet=rapor_servisi.gosterge_paneli(db, modul="IHRACAT"),
        ulke_ozeti=rapor_servisi.ihracat_ulke_ozeti(db),
        urun_bazli=rapor_servisi.urun_bazli_ozet(db, modul="IHRACAT"),
        bekleyenler=rapor_servisi.bekleyen_ozeti(db, modul="IHRACAT"),
        sevk_durumu=rapor_servisi.sevk_durumu(db, modul="IHRACAT"),
    )


@uygulama.get("/ihracat/raporlar/plan-excel")
def ihracat_plan_excel(
    durum: str = "",
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    planlar_listesi = rapor_servisi.planlari_getir(
        db,
        PlanFiltresi(durum=durum or None, arama=arama or None, modul="IHRACAT"),
        limit=5000,
    )
    hedef = ihracat_yukleme_formu.plan_listesi_disa_aktar(
        planlar_listesi, CIKTI_DIZIN / "ihracat_planlari.xlsx"
    )
    return FileResponse(hedef, filename=hedef.name)


# ---------------------------------------------------- ihracat müşteri master datası
@uygulama.get("/masterdata/ihracat-musteriler")
def ihracat_musteriler(
    istek: Request,
    arama: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA")),
    db: Session = Depends(oturum_bagimliligi),
):
    sorgu = select(IhracatMusterisi).order_by(
        IhracatMusterisi.ulke, IhracatMusterisi.musteri_adi
    )
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(
            IhracatMusterisi.musteri_adi.ilike(desen)
            | IhracatMusterisi.ulke.ilike(desen)
            | IhracatMusterisi.ulke_kodu.ilike(desen)
        )
    return sayfa(
        istek,
        "ihracat_musteriler.html",
        kullanici,
        musteriler=db.scalars(sorgu.limit(500)).all(),
        arama=arama,
        sorgu=_sorgu_metni(arama=arama),
        toplam=db.scalar(select(func.count(IhracatMusterisi.id))) or 0,
    )


@uygulama.post("/masterdata/ihracat-musteriler/yukle")
async def ihracat_musterileri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.ihracat_musterilerini_aktar(
            db, dosya.file, dosya.filename or "musteriler.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/ihracat-musteriler", hata=str(hata))
    return yonlendir("/masterdata/ihracat-musteriler", mesaj=f"Müşteri aktarımı: {sonuc.ozet()}")


@uygulama.get("/masterdata/ihracat-musteriler/sablon")
def ihracat_musteri_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA"))):
    hedef = sablonlar.ihracat_musteri_sablonu(CIKTI_DIZIN / "ihracat_musteri_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


# ---------------------------------------------------- ihracat ürün master datası
@uygulama.get("/masterdata/ihracat-urunler")
def ihracat_urunler(
    istek: Request,
    arama: str = "",
    urun_grubu: str = "",
    eksik: str = "",
    durum: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    """Şirketin hesaplama dosyasındaki ürün ölçüleri."""
    from app.models import IhracatUrunu

    filtre = masterdata_servisi.IhracatUrunFiltresi(
        arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
    )
    tumu = masterdata_servisi.ihracat_urunleri_getir(db, filtre)
    return sayfa(
        istek,
        "md_ihracat_urunler.html",
        kullanici,
        urunler=tumu[:EKRAN_LIMITI],
        eslesen=len(tumu),
        ekran_limiti=EKRAN_LIMITI,
        filtre=filtre,
        gruplar=masterdata_servisi.ihracat_urun_gruplari(db),
        eksik_secenekleri=[
            (kod, etiket)
            for kod, (etiket, _) in masterdata_servisi.IHRACAT_EKSIK_KOSULLARI.items()
        ],
        eksikler=masterdata_servisi.ihracat_eksik_ozeti(db),
        sorgu=_sorgu_metni(
            arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
        ),
        toplam=db.scalar(select(func.count(IhracatUrunu.id))) or 0,
    )


@uygulama.get("/masterdata/ihracat-urunler/yeni")
def ihracat_urun_yeni(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "md_ihracat_urun_duzenle.html",
        kullanici,
        urun=None,
        gruplar=masterdata_servisi.ihracat_urun_gruplari(db),
        geri="/masterdata/ihracat-urunler",
    )


@uygulama.post("/masterdata/ihracat-urunler/kaydet")
async def ihracat_urun_kaydet(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    form = await istek.form()
    geri = str(form.get("geri") or "/masterdata/ihracat-urunler")
    urun_kodu = str(form.get("urun_kodu") or "")
    alanlar = {
        ad: str(deger) for ad, deger in form.items() if ad not in {"geri", "urun_kodu"}
    }
    try:
        urun = masterdata_servisi.ihracat_urununu_guncelle(db, urun_kodu, alanlar)
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir(f"/masterdata/ihracat-urunler/{urun_kodu}", hata=str(hata))
    return yonlendir(geri, mesaj=f"{urun.urun_kodu} güncellendi.")


@uygulama.post("/masterdata/ihracat-urunler/yukle")
async def ihracat_urunleri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.ihracat_urunlerini_aktar(
            db, dosya.file, dosya.filename or "hesaplama.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/ihracat-urunler", hata=str(hata))
    return yonlendir("/masterdata/ihracat-urunler", mesaj=f"Ürün aktarımı: {sonuc.ozet()}")


@uygulama.get("/masterdata/ihracat-urunler/sablon")
def ihracat_urun_sablonu(kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA"))):
    hedef = sablonlar.ihracat_urun_sablonu(CIKTI_DIZIN / "ihracat_urun_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/masterdata/ihracat-musteriler/{musteri_id:int}")
def ihracat_musteri_guncelle(
    musteri_id: int,
    arac_tipi: str = Form("TIR"),
    sefer_kodu: str = Form("E"),
    yukleme_tipi: str = Form(""),
    azami_agirlik: str = Form(""),
    aciklama: str = Form(""),
    aktif: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("MASTERDATA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.domain.ihracat import arac_tipi_coz

    musteri = db.get(IhracatMusterisi, musteri_id)
    if musteri is None:
        raise HTTPException(404, "Müşteri bulunamadı")
    musteri.arac_tipi = arac_tipi_coz(arac_tipi).value
    musteri.sefer_kodu = "N" if sefer_kodu.upper().startswith("N") else "E"
    musteri.yukleme_tipi = yukleme_tipi.strip() or None
    rakamlar = "".join(k for k in azami_agirlik if k.isdigit())
    musteri.azami_agirlik = Decimal(rakamlar) if rakamlar else None
    musteri.aciklama = aciklama.strip() or None
    musteri.aktif = aktif
    db.commit()
    return yonlendir("/masterdata/ihracat-musteriler", mesaj=f"{musteri.musteri_adi} güncellendi.")


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


@uygulama.get("/raporlama/izleme")
def raporlama_izleme(
    istek: Request,
    anahtar: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RAPORLAMA")),
    db: Session = Depends(oturum_bagimliligi),
):
    """Teslimat / sipariş numarasından planı bulur.

    Sorgu bütün modüllerde arar; bu yüzden ekran Ring menüsünde değil, Raporlama'da.
    """
    sonuc = rapor_servisi.izleme_sorgusu(db, anahtar) if anahtar.strip() else None
    return sayfa(istek, "izleme.html", kullanici, anahtar=anahtar, sonuc=sonuc)


# ------------------------------------------------------------------- veri yönetimi
@uygulama.get("/veri-yonetimi")
def veri_yonetimi(
    istek: Request,
    kullanici: Kullanici = Depends(modul_yetkisi("YONETIM")),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "veri_yonetimi.html",
        kullanici,
        sayimlar=temizleme.sayimlar(db),
        logo_yuklendi=marka.yuklenen_logo() is not None,
    )


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

    try:
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
    except SQLAlchemyError as hata:
        # Silme yarıda kalırsa veritabanı tutarlı kalsın ve kullanıcı sebebini görsün;
        # sunucu hatası sayfası hiçbir şey anlatmıyor.
        db.rollback()
        return yonlendir(
            "/veri-yonetimi",
            hata=f"Silme tamamlanamadı, hiçbir kayıt silinmedi: {hata.__class__.__name__}",
        )
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


# ------------------------------------------------------------------ manuel planlama
MANUEL_MODULLER = {
    "RING": ("/ring", "Ring"),
    "ROTA": ("/rota", "İç Piyasa"),
    "IHRACAT": ("/ihracat", "İhracat"),
}
"""Manuel planlama ekranı üç modülde de aynı şablonla çalışır.

Ekran seçimi teslimat bazında toplar ve modülün kendi planlama motorunu yalnızca
seçilen teslimatlarla çağırır; kurallar (doluluk, rota, aktarma) aynen işler.
"""


def _manuel_sayfa(
    istek: Request,
    kullanici: Kullanici,
    db: Session,
    modul_kodu: str,
    arama: str,
    depo: str,
):
    taban, modul_adi = MANUEL_MODULLER[modul_kodu]
    teslimatlar = rapor_servisi.planlanabilir_teslimatlar(
        db, modul=modul_kodu, arama=arama or None, depo_kodu=depo or None
    )
    # Depo listesi filtreden bağımsız olmalı; aksi hâlde bir depo seçilince
    # açılır listede yalnızca o depo kalıyor ve seçim değiştirilemiyor.
    tum_teslimatlar = rapor_servisi.planlanabilir_teslimatlar(db, modul=modul_kodu)
    depo_kodlari = sorted(
        {
            kod.strip()
            for t in tum_teslimatlar
            for kod in t["depolar"].split(",")
            if kod.strip()
        }
    )
    return sayfa(
        istek,
        "manuel_plan.html",
        kullanici,
        modul_kodu=modul_kodu,
        modul_adi=modul_adi,
        taban=taban,
        teslimatlar=teslimatlar,
        arama=arama,
        depo=depo,
        depolar=depo_kodlari,
    )


def _manuel_secim(teslimat_nolar: list[str]) -> list[str]:
    return [no.strip() for no in teslimat_nolar if no and no.strip()]


def _manuel_tarih(plan_tarihi: str) -> date:
    return (
        datetime.strptime(plan_tarihi, "%Y-%m-%d").date() if plan_tarihi else date.today()
    )


@uygulama.get("/ring/manuel-plan")
def ring_manuel_plan(
    istek: Request,
    arama: str = "",
    depo: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _manuel_sayfa(istek, kullanici, db, "RING", arama, depo)


@uygulama.post("/ring/manuel-plan/uret")
def ring_manuel_plan_uret(
    teslimat_nolar: list[str] = Form([]),
    plan_tarihi: str = Form(""),
    kalanlari_zorla: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("RING", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    secilenler = _manuel_secim(teslimat_nolar)
    if not secilenler:
        return yonlendir("/ring/manuel-plan", hata="Planlanacak teslimat seçilmedi.")
    try:
        sonuc = plan_servisi.tum_depolari_planla(
            db,
            plan_tarihi=_manuel_tarih(plan_tarihi),
            kullanici=kullanici.kullanici_adi,
            kalanlari_zorla=kalanlari_zorla,
            teslimat_nolar=secilenler,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/ring/manuel-plan", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir(
            "/ring/manuel-plan",
            hata=(
                f"Seçilen {len(secilenler)} teslimattan plan üretilemedi. "
                f"{sonuc.ozet()}"
            ),
        )
    return yonlendir("/ring/planlar", mesaj=f"Manuel planlama — {sonuc.ozet()}")


@uygulama.get("/rota/manuel-plan")
def rota_manuel_plan(
    istek: Request,
    arama: str = "",
    depo: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _manuel_sayfa(istek, kullanici, db, "ROTA", arama, depo)


@uygulama.post("/rota/manuel-plan/uret")
def rota_manuel_plan_uret(
    teslimat_nolar: list[str] = Form([]),
    plan_tarihi: str = Form(""),
    kalanlari_zorla: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    secilenler = _manuel_secim(teslimat_nolar)
    if not secilenler:
        return yonlendir("/rota/manuel-plan", hata="Planlanacak teslimat seçilmedi.")
    try:
        sonuc = ic_piyasa_servisi.plan_uret(
            db,
            plan_tarihi=_manuel_tarih(plan_tarihi),
            kullanici=kullanici.kullanici_adi,
            kalanlari_zorla=kalanlari_zorla,
            teslimat_nolar=secilenler,
            kurallar=masterdata_servisi.kurallari_kur(db),
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/rota/manuel-plan", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir(
            "/rota/manuel-plan",
            hata=(
                f"Seçilen {len(secilenler)} teslimattan plan üretilemedi. "
                f"{sonuc.ozet()}"
            ),
        )
    return yonlendir("/rota/planlar", mesaj=f"Manuel planlama — {sonuc.ozet()}")


@uygulama.get("/ihracat/manuel-plan")
def ihracat_manuel_plan(
    istek: Request,
    arama: str = "",
    depo: str = "",
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _manuel_sayfa(istek, kullanici, db, "IHRACAT", arama, depo)


@uygulama.post("/ihracat/manuel-plan/uret")
def ihracat_manuel_plan_uret(
    teslimat_nolar: list[str] = Form([]),
    plan_tarihi: str = Form(""),
    kalanlari_zorla: bool = Form(False),
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT", duzenleme=True)),
    db: Session = Depends(oturum_bagimliligi),
):
    secilenler = _manuel_secim(teslimat_nolar)
    if not secilenler:
        return yonlendir("/ihracat/manuel-plan", hata="Planlanacak teslimat seçilmedi.")
    try:
        sonuc = ihracat_servisi.plan_uret(
            db,
            plan_tarihi=_manuel_tarih(plan_tarihi),
            kullanici=kullanici.kullanici_adi,
            kalanlari_zorla=kalanlari_zorla,
            teslimat_nolar=secilenler,
        )
        db.commit()
    except PlanHatasi as hata:
        db.rollback()
        return yonlendir("/ihracat/manuel-plan", hata=str(hata))
    if not sonuc.planlar:
        return yonlendir(
            "/ihracat/manuel-plan",
            hata=(
                f"Seçilen {len(secilenler)} teslimattan plan üretilemedi. "
                f"{sonuc.ozet()}"
            ),
        )
    return yonlendir("/ihracat/planlar", mesaj=f"Manuel planlama — {sonuc.ozet()}")


# ------------------------------------------------------------------- master data
@uygulama.get("/masterdata")
def masterdata_ozet(
    istek: Request,
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.models import Depo, IhracatMusterisi, IhracatUrunu, Musteri

    kartlar = [
        {"etiket": "Ürün", "sayi": db.scalar(select(func.count(Urun.id))) or 0,
         "aciklama": "Palet ve araç kapasiteleri", "yol": "/masterdata/urunler"},
        {"etiket": "İç piyasa müşterisi", "sayi": db.scalar(select(func.count(Musteri.id))) or 0,
         "aciklama": "İl, ilçe, bölge, tır girişi", "yol": "/masterdata/musteriler"},
        {"etiket": "İhracat müşterisi",
         "sayi": db.scalar(select(func.count(IhracatMusterisi.id))) or 0,
         "aciklama": "Araç tipi, yükleme tipi, tonaj", "yol": "/masterdata/ihracat-musteriler"},
        {"etiket": "İhracat ürünü",
         "sayi": db.scalar(select(func.count(IhracatUrunu.id))) or 0,
         "aciklama": "Tır / konteyner yükleme adetleri", "yol": "/masterdata/ihracat-urunler"},
        {"etiket": "Ürün grubu",
         "sayi": len(masterdata_servisi.urun_gruplari_ozeti(db)),
         "aciklama": "Ad değiştirme ve birleştirme", "yol": "/masterdata/gruplar"},
        {"etiket": "Ürün bağı",
         "sayi": urun_bagi_servisi.ozet(db)["toplam"],
         "aciklama": "Birlikte sevk edilecek ürünler",
         "yol": "/masterdata/urun-baglari"},
        {"etiket": "Depo", "sayi": db.scalar(select(func.count(Depo.id))) or 0,
         "aciklama": "Kod, tesis, form etiketi", "yol": "/masterdata/depolar"},
    ]
    return sayfa(
        istek,
        "masterdata.html",
        kullanici,
        kartlar=kartlar,
        eksikler=masterdata_servisi.urun_eksik_ozeti(db),
    )


@uygulama.get("/masterdata/urunler")
def md_urunler(
    istek: Request,
    arama: str = "",
    urun_grubu: str = "",
    eksik: str = "",
    durum: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    filtre = masterdata_servisi.UrunFiltresi(
        arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
    )
    tumu = masterdata_servisi.urunleri_getir(db, filtre)
    # Ekran ilk 500 kaydı gösterir; indirilen dosya filtrenin tamamını içerir.
    # 2.585 ürünün hepsini basmak sayfayı megabaytlarca büyütüyor ve tarayıcıyı
    # yoruyor, üstelik kimse 2.585 satırı ekranda taramıyor.
    return sayfa(
        istek,
        "md_urunler.html",
        kullanici,
        urunler=tumu[:EKRAN_LIMITI],
        toplam=len(tumu),
        ekran_limiti=EKRAN_LIMITI,
        filtre=filtre,
        gruplar=sorted(masterdata_servisi.urun_gruplari(db)),
        eksik_secenekleri=[
            (kod, etiket)
            for kod, (etiket, _) in masterdata_servisi.EKSIK_KOSULLARI.items()
        ],
        sorgu=_sorgu_metni(
            arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
        ),
    )


@uygulama.get("/masterdata/urunler/excel")
def md_urunler_excel(
    arama: str = "",
    urun_grubu: str = "",
    eksik: str = "",
    durum: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    """Ekrandaki filtrenin **aynısını** uygular; inen dosya görülen listedir."""
    filtre = masterdata_servisi.UrunFiltresi(
        arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
    )
    hedef = masterdata_servisi.disari_aktar(
        masterdata_servisi.urunleri_getir(db, filtre),
        veri_formatlari.URUN_ALANLARI,
        masterdata_servisi.URUN_DEGERLERI,
        CIKTI_DIZIN / "urun_masterdata.xlsx",
        "Ürünler",
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/masterdata/urunler/sablon")
def md_urun_sablonu(kullanici: Kullanici = Depends(MD_YETKI)):
    hedef = sablonlar.urun_sablonu(CIKTI_DIZIN / "urun_masterdata_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post("/masterdata/urunler/yukle")
async def md_urunleri_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.urunleri_aktar(
            db, dosya.file, dosya.filename or "urunler.xlsx", kullanici.kullanici_adi
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/urunler", hata=str(hata))
    return yonlendir("/masterdata/urunler", mesaj=f"Ürün aktarımı: {sonuc.ozet()}")


@uygulama.get("/masterdata/urunler/yeni")
def md_urun_yeni(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "md_urun_duzenle.html",
        kullanici,
        urun=None,
        gruplar=sorted(masterdata_servisi.urun_gruplari(db)),
        geri="/masterdata/urunler",
    )


@uygulama.post("/masterdata/urunler/kaydet")
async def md_urun_kaydet(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    form = await istek.form()
    geri = str(form.get("geri") or "/masterdata/urunler")
    urun_kodu = str(form.get("urun_kodu") or "")
    alanlar = {ad: str(deger) for ad, deger in form.items() if ad not in {"geri", "urun_kodu"}}
    try:
        urun = masterdata_servisi.urunu_guncelle(db, urun_kodu, alanlar)
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir(f"/masterdata/urunler/{urun_kodu}", hata=str(hata))
    return yonlendir(geri, mesaj=f"{urun.urun_kodu} güncellendi.")


@uygulama.get("/masterdata/urunler/{urun_kodu:path}")
def md_urun_duzenle(
    istek: Request,
    urun_kodu: str,
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    urun = db.scalar(select(Urun).where(Urun.urun_kodu == urun_kodu))
    if urun is None:
        raise HTTPException(404, "Ürün bulunamadı")
    return sayfa(
        istek,
        "md_urun_duzenle.html",
        kullanici,
        urun=urun,
        gruplar=sorted(masterdata_servisi.urun_gruplari(db)),
        geri="/masterdata/urunler",
    )


@uygulama.post("/masterdata/musteriler/ek-bilgi")
async def md_musteri_ek_bilgi(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    """Sahanın cari kod / sevk tipi listesini müşteri kayıtlarına işler."""
    try:
        sonuc = musteri_ek_bilgi.ek_bilgileri_aktar(db, dosya.file)
        db.commit()
    except (ExcelHatasi, OSError, KeyError) as hata:
        db.rollback()
        return yonlendir("/masterdata/musteriler", hata=f"Dosya okunamadı: {hata}")
    if sonuc.eslesmeyenler:
        musteri_ek_bilgi.eslesmeyen_raporu(
            sonuc, CIKTI_DIZIN / "eslesmeyen_musteriler.xlsx"
        )
    return yonlendir("/masterdata/musteriler", mesaj=sonuc.ozet())


@uygulama.get("/masterdata/musteriler/eslesmeyenler")
def md_eslesmeyen_musteriler(kullanici: Kullanici = Depends(MD_YETKI)):
    """Son yüklemede eşleşmeyen adların listesi."""
    hedef = CIKTI_DIZIN / "eslesmeyen_musteriler.xlsx"
    if not hedef.exists():
        raise HTTPException(404, "Henüz eşleşmeyen kayıt listesi üretilmedi.")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/masterdata/musteriler/excel")
def md_musteriler_excel(
    arama: str = "",
    tir: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    hedef = masterdata_servisi.disari_aktar(
        rapor_servisi.musterileri_getir(db, arama or None, tir or None, limit=20000),
        veri_formatlari.MUSTERI_ALANLARI,
        masterdata_servisi.MUSTERI_DEGERLERI,
        CIKTI_DIZIN / "ic_piyasa_masterdata.xlsx",
        "Müşteriler",
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/masterdata/ihracat-musteriler/excel")
def md_ihracat_musteriler_excel(
    arama: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    """Ekrandaki aramanın aynısını uygular; inen dosya görülen listedir."""
    from app.models import IhracatMusterisi

    sorgu = select(IhracatMusterisi).order_by(IhracatMusterisi.musteri_adi)
    if arama:
        desen = f"%{arama.strip()}%"
        sorgu = sorgu.where(
            IhracatMusterisi.musteri_adi.ilike(desen)
            | IhracatMusterisi.ulke.ilike(desen)
            | IhracatMusterisi.ulke_kodu.ilike(desen)
        )
    hedef = masterdata_servisi.disari_aktar(
        list(db.scalars(sorgu).all()),
        veri_formatlari.IHRACAT_MUSTERI_ALANLARI,
        masterdata_servisi.IHRACAT_MUSTERI_DEGERLERI,
        CIKTI_DIZIN / "ihracat_masterdata.xlsx",
        "İhracat müşterileri",
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/masterdata/ihracat-urunler/excel")
def md_ihracat_urunler_excel(
    arama: str = "",
    urun_grubu: str = "",
    eksik: str = "",
    durum: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    """Ekrandaki filtrenin **aynısını** uygular; inen dosya görülen listedir."""
    filtre = masterdata_servisi.IhracatUrunFiltresi(
        arama=arama, urun_grubu=urun_grubu, eksik=eksik, durum=durum
    )
    hedef = masterdata_servisi.disari_aktar(
        masterdata_servisi.ihracat_urunleri_getir(db, filtre),
        veri_formatlari.IHRACAT_URUN_ALANLARI,
        masterdata_servisi.IHRACAT_URUN_DEGERLERI,
        CIKTI_DIZIN / "ihracat_urun_masterdata.xlsx",
        "İhracat ürünleri",
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get("/masterdata/depolar")
def md_depolar(
    istek: Request,
    kod: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.models import Depo

    masterdata_servisi.depolari_yukle(db)
    db.commit()
    secili = db.scalar(select(Depo).where(Depo.kod == kod)) if kod else None
    return sayfa(
        istek,
        "md_depolar.html",
        kullanici,
        depolar=masterdata_servisi.depolari_getir(db),
        secili=secili,
    )


@uygulama.post("/masterdata/depolar/kaydet")
async def md_depo_kaydet(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    form = await istek.form()
    kod = str(form.get("kod") or "")
    alanlar = {ad: str(deger) for ad, deger in form.items() if ad != "kod"}
    try:
        depo = masterdata_servisi.depoyu_kaydet(db, kod, alanlar)
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/depolar", hata=str(hata))
    return yonlendir("/masterdata/depolar", mesaj=f"{depo.kod} deposu kaydedildi.")


SABIT_KURALLAR = [
    {
        "ad": "Anahtar değer palete yuvarlanmaz",
        "deger": "Σ miktar / yükleme adeti",
        "dayanak": "2025'in 2.048 gerçek tırında ham ölçünün medyanı 1,000; palete "
                   "yuvarlanmış ölçününki 1,263 ve araçların %94,6'sı 1,00 üstünde.",
    },
    {
        "ad": "Araç doluluk üst limiti",
        "deger": "1,00 anahtar",
        "dayanak": "Gerçek tırların medyanı tam 1,00. Alt limit depo profilinde tanımlı.",
    },
    {
        "ad": "Parsiyel yapılabilen depolar",
        "deger": "64, -1 ve 74 (64 ile -1 birlikte, 74 ayrı)",
        "dayanak": "2025'in 691 parsiyel aracındaki satırların %99,95'i bu depolardan.",
    },
    {
        "ad": "Parsiyel aktarma merkezleri",
        "deger": "Ankara / İstanbul / Bursa / Eskişehir",
        "dayanak": "İl tablosu app/domain/aktarma.py; 2025 parsiyel araçlarındaki il "
                   "birlikteliğiyle uyumlu.",
    },
    {
        "ad": "İller arası mesafe",
        "deger": "81 il merkez koordinatı × 1,25 karayolu katsayısı",
        "dayanak": "Elde mevcut Eskişehir mesafe tablosunu medyan %6 hatayla üretiyor.",
    },
    {
        "ad": "Depo kapasite profilleri",
        "deger": "Bütün depolar tır bazında, anahtar değerle",
        "dayanak": "app/config.py DEPO_PROFILLERI.",
    },
]
"""Ekrandan değiştirilmeyen kurallar ve dayanakları; sistem ekranında listelenir."""


@uygulama.get("/masterdata/sistem")
def md_sistem(
    istek: Request,
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    return sayfa(
        istek,
        "md_sistem.html",
        kullanici,
        ayarlar=masterdata_servisi.ayar_satirlari(db),
        sabit_kurallar=SABIT_KURALLAR,
    )


@uygulama.post("/masterdata/sistem")
async def md_sistem_kaydet(
    istek: Request,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.models import Ayar

    form = await istek.form()
    if form.get("varsayilana_don"):
        db.execute(delete(Ayar))
        db.commit()
        return yonlendir("/masterdata/sistem", mesaj="Bütün ayarlar varsayılana döndü.")
    try:
        degisenler = masterdata_servisi.ayarlari_kaydet(
            db, {ad: str(deger) for ad, deger in form.items()}, kullanici.kullanici_adi
        )
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/sistem", hata=str(hata))
    if not degisenler:
        return yonlendir("/masterdata/sistem", mesaj="Değişiklik yok.")
    return yonlendir(
        "/masterdata/sistem", mesaj="Kaydedildi — " + " · ".join(degisenler)
    )


# Eski adresler: yer imi ve kayıtlı bağlantılar kırılmasın diye yönlendirilir.
ESKI_MASTERDATA_ADRESLERI = {
    "/urunler": "/masterdata/urunler",
    "/rota/musteriler": "/masterdata/musteriler",
    "/ihracat/musteriler": "/masterdata/ihracat-musteriler",
    "/ihracat/urunler": "/masterdata/ihracat-urunler",
}

for _eski, _yeni in ESKI_MASTERDATA_ADRESLERI.items():
    uygulama.add_api_route(
        _eski,
        (lambda hedef: lambda: RedirectResponse(hedef, status_code=308))(_yeni),
        methods=["GET"],
        include_in_schema=False,
    )


# ------------------------------------------------------- araç içi yerleşim (istif)
ISTIF_MODULLERI = {"RING": "/ring", "ROTA": "/rota", "IHRACAT": "/ihracat"}


def _istif_sayfasi(
    istek: Request, kullanici: Kullanici, db: Session, plan_id: int, modul_kodu: str
):
    plan = plan_getir(db, plan_id)
    istif = istif_servisi.istif_plani(db, plan)
    duraklar = istif_servisi.durak_ozeti(istif)
    for durak in duraklar:
        durak["renk"] = istif_servisi.durak_rengi(durak["sira"])
    on, arka = istif.agirlik_dagilimi()
    toplam = on + arka
    return sayfa(
        istek,
        "istif.html",
        kullanici,
        plan=plan,
        istif=istif,
        duraklar=duraklar,
        cizim=istif_servisi.cizim_verisi(istif),
        yukleme=istif_servisi.yukleme_sirasi(istif),
        kirik_palet=sum(1 for y in istif.yerlesimler if y.yuk.kirik_mi),
        on_oran=int(on / toplam * 100) if toplam else 0,
        modul_kodu=modul_kodu,
        taban=ISTIF_MODULLERI[modul_kodu],
    )


@uygulama.get("/ring/planlar/{plan_id}/yerlesim")
def ring_istif(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("RING")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _istif_sayfasi(istek, kullanici, db, plan_id, "RING")


@uygulama.get("/rota/planlar/{plan_id}/yerlesim")
def rota_istif(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("ROTA")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _istif_sayfasi(istek, kullanici, db, plan_id, "ROTA")


@uygulama.get("/ihracat/planlar/{plan_id}/yerlesim")
def ihracat_istif(
    istek: Request,
    plan_id: int,
    kullanici: Kullanici = Depends(modul_yetkisi("IHRACAT")),
    db: Session = Depends(oturum_bagimliligi),
):
    return _istif_sayfasi(istek, kullanici, db, plan_id, "IHRACAT")


@uygulama.get("/masterdata/ihracat-urunler/{urun_kodu:path}")
def ihracat_urun_duzenle(
    istek: Request,
    urun_kodu: str,
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.models import IhracatUrunu

    urun = db.scalar(
        select(IhracatUrunu).where(IhracatUrunu.urun_kodu == urun_kodu)
    )
    if urun is None:
        raise HTTPException(404, "Ürün bulunamadı")
    return sayfa(
        istek,
        "md_ihracat_urun_duzenle.html",
        kullanici,
        urun=urun,
        gruplar=masterdata_servisi.ihracat_urun_gruplari(db),
        geri="/masterdata/ihracat-urunler",
    )


# --------------------------------------------------------------- ürün grupları
@uygulama.get("/masterdata/gruplar")
def md_gruplar(
    istek: Request,
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    gruplar = masterdata_servisi.urun_gruplari_ozeti(db)
    listeler: dict[str, list[str]] = {}
    for g in gruplar:
        listeler.setdefault(g["kapsam"], []).append(g["ad"])
    return sayfa(
        istek,
        "md_gruplar.html",
        kullanici,
        gruplar=gruplar,
        cakisanlar=[g for g in gruplar if g["cakisanlar"]],
        grup_listeleri={k: sorted(v) for k, v in listeler.items()},
        grupsuzlar=masterdata_servisi.grupsuz_urun_sayisi(db),
        kapsam_adlari=masterdata_servisi.GRUP_ADLARI,
    )


@uygulama.post("/masterdata/gruplar/ad")
def md_grup_adi(
    kapsam: str = Form(...),
    eski_ad: str = Form(...),
    yeni_ad: str = Form(...),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    """Grup adını değiştirir; ad zaten varsa iki grup birleşir."""
    try:
        sayi = masterdata_servisi.grubu_yeniden_adlandir(db, kapsam, eski_ad, yeni_ad)
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/gruplar", hata=str(hata))
    if not sayi:
        return yonlendir("/masterdata/gruplar", mesaj="Değişiklik yok.")
    return yonlendir(
        "/masterdata/gruplar",
        mesaj=f"{eski_ad} → {yeni_ad}: {sayi} ürün güncellendi.",
    )


@uygulama.post("/masterdata/gruplar/sil")
def md_grup_sil(
    kapsam: str = Form(...),
    ad: str = Form(...),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sayi = masterdata_servisi.grubu_sil(db, kapsam, ad)
        db.commit()
    except masterdata_servisi.MasterDataHatasi as hata:
        db.rollback()
        return yonlendir("/masterdata/gruplar", hata=str(hata))
    return yonlendir(
        "/masterdata/gruplar", mesaj=f"{ad} grubu {sayi} üründen kaldırıldı."
    )


# ------------------------------------------------- birlikte sevk edilecek ürünler
BAG_YOLU = "/masterdata/urun-baglari"


@uygulama.get(BAG_YOLU)
def md_urun_baglari(
    istek: Request,
    arama: str = "",
    tip: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    from app.models import BagTipi

    return sayfa(
        istek,
        "md_urun_baglari.html",
        kullanici,
        baglar=urun_bagi_servisi.baglari_getir(db, arama=arama, tip=tip),
        ozet=urun_bagi_servisi.ozet(db),
        arama=arama,
        tip=tip,
        tipler=[t.value for t in BagTipi],
        sorgu=_sorgu_metni(arama=arama, tip=tip),
    )


@uygulama.post(BAG_YOLU + "/kaydet")
def md_urun_bagi_kaydet(
    ana_urun_kodu: str = Form(...),
    bagli_urun_kodu: str = Form(...),
    tip: str = Form("AKSESUAR"),
    aciklama: str = Form(""),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        urun_bagi_servisi.bag_kaydet(db, ana_urun_kodu, bagli_urun_kodu, tip, aciklama)
        db.commit()
    except urun_bagi_servisi.BagHatasi as hata:
        db.rollback()
        return yonlendir(BAG_YOLU, hata=str(hata))
    return yonlendir(
        BAG_YOLU, mesaj=f"{ana_urun_kodu} + {bagli_urun_kodu} bağı kaydedildi."
    )


@uygulama.post(BAG_YOLU + "/{bag_id}/sil")
def md_urun_bagi_sil(
    bag_id: int,
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        urun_bagi_servisi.bagi_sil(db, bag_id)
        db.commit()
    except urun_bagi_servisi.BagHatasi as hata:
        db.rollback()
        return yonlendir(BAG_YOLU, hata=str(hata))
    return yonlendir(BAG_YOLU, mesaj="Bağ silindi.")


@uygulama.get(BAG_YOLU + "/excel")
def md_urun_baglari_excel(
    arama: str = "",
    tip: str = "",
    kullanici: Kullanici = Depends(MD_YETKI),
    db: Session = Depends(oturum_bagimliligi),
):
    """Ekrandaki filtrenin aynısını uygular; inen dosya doldurulup geri yüklenebilir."""
    hedef = urun_bagi_servisi.disari_aktar(
        urun_bagi_servisi.baglari_getir(db, arama=arama, tip=tip, limit=100000),
        CIKTI_DIZIN / "urun_baglari.xlsx",
    )
    return FileResponse(hedef, filename=hedef.name)


@uygulama.get(BAG_YOLU + "/sablon")
def md_urun_bagi_sablonu(kullanici: Kullanici = Depends(MD_YETKI)):
    hedef = sablonlar.urun_bagi_sablonu(CIKTI_DIZIN / "urun_baglari_sablonu.xlsx")
    return FileResponse(hedef, filename=hedef.name)


@uygulama.post(BAG_YOLU + "/yukle")
async def md_urun_baglari_yukle(
    dosya: UploadFile = File(...),
    kullanici: Kullanici = Depends(MD_DUZENLEME),
    db: Session = Depends(oturum_bagimliligi),
):
    try:
        sonuc = ice_aktarim.urun_baglarini_aktar(
            db, dosya.file, dosya.filename or "urun_baglari.xlsx",
            kullanici.kullanici_adi,
        )
        db.commit()
    except ExcelHatasi as hata:
        db.rollback()
        return yonlendir(BAG_YOLU, hata=str(hata))
    mesaj = f"Ürün bağı aktarımı: {sonuc.ozet()}"
    if sonuc.hatalar:
        # En sık hata "ürün master datada yok"; sebebi görünmezse kullanıcı
        # dosyanın neden reddedildiğini anlamıyor.
        ornekler = "; ".join(
            f"satır {h.satir_no}: {h.mesaj}" for h in sonuc.hatalar[:3]
        )
        mesaj += f" — {ornekler}"
        if len(sonuc.hatalar) > 3:
            mesaj += f" (+{len(sonuc.hatalar) - 3} hata daha)"
    return yonlendir(BAG_YOLU, mesaj=mesaj)
