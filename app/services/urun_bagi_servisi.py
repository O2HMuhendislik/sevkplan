"""Birlikte sevk edilmesi gereken ürünler: set ve aksesuar bağları.

**Neden var.** Şirketin ürün master datasında 'header kod' diye bir alan var ve
kodda ana ürün ile aksesuarı aynı planda tutmak için kullanılıyor. Ama Vaillant
ürünlerinde bu alan hiç doldurulmamış: master datadaki 2.585 ürünün tamamında boş.
Bağ bilgisi olmayınca kombi bir araca biniyor, bacası iki gün sonra başka bir araca
düşüyor — sahada müşteri şikâyetine dönüşen durum bu.

**Neden ürün kodu üzerinden.** Bugünkü tek koruma teslimat bazlı: bir teslimatın
satırları bölünmüyor ve bölünürse oransal bölünüyor, böylece aksesuar ana ürünle
kalıyor. Stoklar farklı zamanlarda geldiği için aynı siparişin parçaları **farklı
teslimat numaraları** alabiliyor; o anda teslimat bazlı koruma kopuyor. Bağ bu
yüzden ürün kodları arasında kurulur ve **aynı müşterinin bekleyen bütün
teslimatlarında** aranır.

İki bağ tipi var:
  * ``SET``      — bir bütünün iki parçası (klima iç ünite + dış ünite). Simetrik:
                   hangisi planda olursa olsun diğeri aranır.
  * ``AKSESUAR`` — ana ürünün yanında gitmesi gereken parça (baca, montaj seti).
                   Tek yönlü: aksesuar ana ürünsüz gitmemeli; ana ürün, aksesuarı
                   sipariş edilmemişse tek başına gidebilir.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BagTipi, SiparisDurumu, SiparisSatiri, Urun, UrunBagi
from app.services.veri_formatlari import URUN_BAGI_ALANLARI


class BagHatasi(Exception):
    """Ekrana gösterilecek, kullanıcının düzeltebileceği hata."""


@dataclass(frozen=True)
class BagKaydi:
    """Bir ürünün karşısındaki bağ; `bag_haritasi` bunları üretir."""

    karsi_kod: str
    tip: BagTipi
    karsi_ana_mi: bool
    """Karşıdaki ürün ana ürün mü? Doğruysa bu ürün onun aksesuarıdır ve tek
    başına sevk edilmemelidir."""


def _kod(deger: str | None) -> str:
    return (deger or "").strip()


# --------------------------------------------------------------------- okuma
def bag_haritasi(db: Session) -> dict[str, list[BagKaydi]]:
    """Ürün kodu -> o üründen beklenen karşı ürünler.

    SET bağı iki yöne de yazılır; AKSESUAR bağı da iki yöne yazılır ama yönü
    `karsi_ana_mi` ile korunur.
    """
    harita: dict[str, list[BagKaydi]] = defaultdict(list)
    for bag in db.scalars(select(UrunBagi).where(UrunBagi.aktif.is_(True))).all():
        harita[bag.ana_urun_kodu].append(
            BagKaydi(bag.bagli_urun_kodu, bag.tip, karsi_ana_mi=False)
        )
        harita[bag.bagli_urun_kodu].append(
            BagKaydi(bag.ana_urun_kodu, bag.tip, karsi_ana_mi=bag.tip is BagTipi.AKSESUAR)
        )
    return dict(harita)


def baglari_getir(
    db: Session, arama: str = "", tip: str = "", limit: int = 1000
) -> list[dict]:
    """Ekran listesi: bağ + iki ürünün adı."""
    sorgu = select(UrunBagi).order_by(UrunBagi.ana_urun_kodu, UrunBagi.bagli_urun_kodu)
    if tip:
        sorgu = sorgu.where(UrunBagi.tip == BagTipi(tip))
    baglar = list(db.scalars(sorgu.limit(limit)).all())

    kodlar = {b.ana_urun_kodu for b in baglar} | {b.bagli_urun_kodu for b in baglar}
    adlar = {
        u.urun_kodu: u
        for u in db.scalars(select(Urun).where(Urun.urun_kodu.in_(kodlar))).all()
    }

    satirlar = []
    for bag in baglar:
        ana = adlar.get(bag.ana_urun_kodu)
        bagli = adlar.get(bag.bagli_urun_kodu)
        satir = {
            "id": bag.id,
            "ana_urun_kodu": bag.ana_urun_kodu,
            "ana_urun_adi": ana.urun_adi if ana else "",
            "ana_grubu": (ana.urun_grubu if ana else "") or "",
            "bagli_urun_kodu": bag.bagli_urun_kodu,
            "bagli_urun_adi": bagli.urun_adi if bagli else "",
            "bagli_grubu": (bagli.urun_grubu if bagli else "") or "",
            "tip": bag.tip.value,
            "kaynak": bag.kaynak,
            "aciklama": bag.aciklama or "",
            "aktif": bag.aktif,
            # Master datada olmayan kod bağı sessizce işlevsiz bırakır; görünür olsun.
            "tanimsiz": [
                kod
                for kod, kayit in ((bag.ana_urun_kodu, ana), (bag.bagli_urun_kodu, bagli))
                if kayit is None
            ],
        }
        if arama:
            desen = arama.strip().lower()
            havuz = " ".join(
                str(satir[alan]).lower()
                for alan in ("ana_urun_kodu", "ana_urun_adi", "bagli_urun_kodu",
                             "bagli_urun_adi", "aciklama")
            )
            if desen not in havuz:
                continue
        satirlar.append(satir)
    return satirlar


def ozet(db: Session) -> dict:
    baglar = list(db.scalars(select(UrunBagi)).all())
    kodlar = {b.ana_urun_kodu for b in baglar} | {b.bagli_urun_kodu for b in baglar}
    return {
        "toplam": len(baglar),
        "set": sum(1 for b in baglar if b.tip is BagTipi.SET),
        "aksesuar": sum(1 for b in baglar if b.tip is BagTipi.AKSESUAR),
        "urun": len(kodlar),
    }


# --------------------------------------------------------------------- yazma
def bag_kaydet(
    db: Session,
    ana_urun_kodu: str,
    bagli_urun_kodu: str,
    tip: str,
    aciklama: str | None = "",
    kaynak: str = "ELLE",
) -> UrunBagi:
    # Excel'den gelen boş hücre None olur; ekrandan gelen boş alan "" olur.
    ana, bagli, aciklama = _kod(ana_urun_kodu), _kod(bagli_urun_kodu), _kod(aciklama)
    if not ana or not bagli:
        raise BagHatasi("İki ürün kodu da gerekli.")
    if ana == bagli:
        raise BagHatasi("Bir ürün kendisine bağlanamaz.")
    try:
        bag_tipi = BagTipi(tip)
    except ValueError:
        raise BagHatasi(f"Bilinmeyen bağ tipi: {tip}") from None

    tanimli = {
        u.urun_kodu
        for u in db.scalars(select(Urun).where(Urun.urun_kodu.in_({ana, bagli}))).all()
    }
    eksik = sorted({ana, bagli} - tanimli)
    if eksik:
        raise BagHatasi(
            f"Master datada tanımlı olmayan ürün kodu: {', '.join(eksik)}. "
            "Önce ürünü Master Data > Ürünler ekranından tanımlayın."
        )

    # Aynı çift ters sırada da girilmiş olabilir; tek kayıt tutulur.
    mevcut = db.scalar(
        select(UrunBagi).where(
            ((UrunBagi.ana_urun_kodu == ana) & (UrunBagi.bagli_urun_kodu == bagli))
            | ((UrunBagi.ana_urun_kodu == bagli) & (UrunBagi.bagli_urun_kodu == ana))
        )
    )
    if mevcut is not None:
        mevcut.ana_urun_kodu, mevcut.bagli_urun_kodu = ana, bagli
        mevcut.tip = bag_tipi
        mevcut.aciklama = aciklama or None
        mevcut.kaynak = kaynak
        mevcut.aktif = True
        db.flush()
        return mevcut

    bag = UrunBagi(
        ana_urun_kodu=ana,
        bagli_urun_kodu=bagli,
        tip=bag_tipi,
        kaynak=kaynak,
        aciklama=aciklama or None,
    )
    db.add(bag)
    db.flush()
    return bag


def bagi_sil(db: Session, bag_id: int) -> None:
    bag = db.get(UrunBagi, bag_id)
    if bag is None:
        raise BagHatasi("Bağ bulunamadı.")
    db.delete(bag)
    db.flush()


# ------------------------------------------------------------------- uyarılar
def _musteri_anahtari(satir: SiparisSatiri) -> str:
    """Satırın müşterisi. Bağ aynı müşteri içinde aranır: farklı bayilere giden
    aynı ürünlerin birbirini tamamlaması beklenmez."""
    for aday in (satir.bayi_adi, satir.alici_firma, satir.sevk_adresi):
        metin = (aday or "").strip()
        if metin:
            return metin.upper()
    return f"TESLİMAT {satir.teslimat_no}"


AGIRLIK_SIRASI = {"YUKSEK": 0, "ORTA": 1}


def plan_uyarilari(db: Session, plan) -> list[dict]:
    """Planda parçası eksik kalan ürünleri bulur.

    Üç durum ayrılır, çünkü operatörün yapacağı iş üçünde de farklı:

    1. **Eksik parça başka bir planda** — asıl hata budur: iki parça aynı gün
       ayrı araçlara binmiş. Plan birleştirilmeli.
    2. **Eksik parça beklemede** — henüz plana girmemiş; bu plana eklenebilir.
    3. **Eksik parça sipariş edilmemiş** — yapılacak bir şey yok; SET bağında yine
       de uyarılır (yarım klima sevk edilmemeli), aksesuar bağında sessiz geçilir.
    """
    harita = bag_haritasi(db)
    if not harita or not plan.satirlar:
        return []

    plandakiler: dict[str, set[str]] = defaultdict(set)
    adlar: dict[str, str] = {}
    for satir in plan.satirlar:
        plandakiler[_musteri_anahtari(satir)].add(satir.urun_kodu)
        adlar.setdefault(satir.urun_kodu, satir.urun_adi or "")

    ilgili_kodlar = {
        kayit.karsi_kod
        for kodlar in plandakiler.values()
        for kod in kodlar
        for kayit in harita.get(kod, ())
    }
    if not ilgili_kodlar:
        return []

    # Aranan parça nerede: başka bir planda mı, beklemede mi?
    baska_plan: dict[tuple[str, str], str] = {}
    bekleyen: dict[tuple[str, str], int] = defaultdict(int)
    diger_satirlar = db.scalars(
        select(SiparisSatiri).where(
            SiparisSatiri.urun_kodu.in_(ilgili_kodlar),
            SiparisSatiri.modul == plan.modul,
            SiparisSatiri.id.notin_([s.id for s in plan.satirlar]),
        )
    ).all()
    for satir in diger_satirlar:
        anahtar = (_musteri_anahtari(satir), satir.urun_kodu)
        adlar.setdefault(satir.urun_kodu, satir.urun_adi or "")
        if satir.durum is SiparisDurumu.BEKLEMEDE:
            bekleyen[anahtar] += 1
        elif satir.plan is not None and satir.plan.id != plan.id:
            baska_plan.setdefault(anahtar, satir.plan.sefer_no)

    eksik_adlar = {
        u.urun_kodu: u.urun_adi
        for u in db.scalars(select(Urun).where(Urun.urun_kodu.in_(ilgili_kodlar))).all()
    }

    uyarilar: list[dict] = []
    gorulen: set[tuple[str, str, str]] = set()
    for musteri, kodlar in sorted(plandakiler.items()):
        for kod in sorted(kodlar):
            for kayit in harita.get(kod, ()):
                if kayit.karsi_kod in kodlar:
                    continue  # parça bu planda, sorun yok
                anahtar = (musteri, kayit.karsi_kod)
                sefer = baska_plan.get(anahtar)
                bekliyor = bool(bekleyen.get(anahtar))

                if kayit.tip is BagTipi.SET:
                    agirlik, gerekce = "YUKSEK", "Setin diğer parçası bu planda yok."
                elif kayit.karsi_ana_mi:
                    agirlik = "YUKSEK"
                    gerekce = "Aksesuar, ana ürünü olmadan sevk ediliyor."
                elif sefer or bekliyor:
                    agirlik = "ORTA"
                    gerekce = "Aksesuarı sipariş edilmiş ama bu planda değil."
                else:
                    continue  # aksesuar hiç sipariş edilmemiş: yapacak bir şey yok

                if sefer:
                    gerekce += f" {sefer} planında."
                elif bekliyor:
                    gerekce += " Beklemede; bu plana eklenebilir."
                else:
                    gerekce += " Sipariş edilmemiş."

                imza = (musteri, kod, kayit.karsi_kod)
                if imza in gorulen:
                    continue
                gorulen.add(imza)
                uyarilar.append({
                    "musteri": musteri,
                    "urun_kodu": kod,
                    "urun_adi": adlar.get(kod, ""),
                    "eksik_kod": kayit.karsi_kod,
                    "eksik_adi": eksik_adlar.get(kayit.karsi_kod, ""),
                    "tip": kayit.tip.value,
                    "agirlik": agirlik,
                    "gerekce": gerekce,
                    "diger_plan": sefer,
                    "bekliyor": bekliyor,
                })
    uyarilar.sort(key=lambda u: (AGIRLIK_SIRASI[u["agirlik"]], u["musteri"], u["urun_kodu"]))
    return uyarilar


# ------------------------------------------------------------------- Excel
BAG_DEGERLERI = {
    "ana_urun_kodu": lambda s: s["ana_urun_kodu"],
    "bagli_urun_kodu": lambda s: s["bagli_urun_kodu"],
    "tip": lambda s: s["tip"],
    "aciklama": lambda s: s["aciklama"],
}


def disari_aktar(satirlar: list[dict], hedef: Path) -> Path:
    """Ekrandaki listeyi, içe aktarımın tanıdığı başlıklarla Excel'e yazar.

    İnen dosya doldurulup doğrudan geri yüklenebilir; başlıklar da şablon da tek
    kaynaktan (`veri_formatlari.URUN_BAGI_ALANLARI`) geliyor.
    """
    from app.services import masterdata_servisi

    return masterdata_servisi.disari_aktar(
        satirlar, URUN_BAGI_ALANLARI, BAG_DEGERLERI, hedef, "Ürün Bağları"
    )
