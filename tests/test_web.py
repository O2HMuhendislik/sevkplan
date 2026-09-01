"""Web katmanı duman testi: ekranlar açılıyor ve uçtan uca akış çalışıyor mu?"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.db import oturum_bagimliligi
from app.main import uygulama


@pytest.fixture()
def istemci(tmp_path):
    motor = create_engine(f"sqlite:///{tmp_path/'test.db'}", future=True)
    models.Temel.metadata.create_all(motor)
    fabrika = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)

    def oturum_ver():
        db = fabrika()
        try:
            yield db
        finally:
            db.close()

    uygulama.dependency_overrides[oturum_bagimliligi] = oturum_ver
    with TestClient(uygulama) as istemci:
        yield istemci
    uygulama.dependency_overrides.clear()


def sorgu(cevap) -> str:
    """Yönlendirme sonrası URL'deki mesaj/hata parametresini okunur metne çevirir."""
    from urllib.parse import unquote_plus

    ham = cevap.url.query
    return unquote_plus(ham.decode() if isinstance(ham, bytes) else ham)


def kitap(basliklar, satirlar) -> BytesIO:
    calisma_kitabi = Workbook()
    sayfa = calisma_kitabi.active
    sayfa.append(basliklar)
    for satir in satirlar:
        sayfa.append(satir)
    tampon = BytesIO()
    calisma_kitabi.save(tampon)
    tampon.seek(0)
    return tampon


@pytest.mark.parametrize(
    "yol", ["/", "/urunler", "/siparisler", "/planlar", "/raporlar", "/izleme"]
)
def test_ekranlar_acilir(istemci, yol):
    cevap = istemci.get(yol)
    assert cevap.status_code == 200
    assert "SEVKİYAT PLANLAMA" in cevap.text


def test_uctan_uca_akis(istemci):
    urun_dosyasi = kitap(
        ["StokKodu", "StokAdi", "Ürün Grubu", "Palet içi adet", "Tır yükleme adeti"],
        [["KMB-24", "Kombi 24 kW", "KOMBİ", 10, 100]],
    )
    cevap = istemci.post(
        "/urunler/yukle", files={"dosya": ("urunler.xlsx", urun_dosyasi)}
    )
    assert cevap.status_code == 200 and "1 yeni" in sorgu(cevap)

    siparis_dosyasi = kitap(
        ["Sipariş No", "Teslimat No", "StokKodu", "Adet", "Depo  Kodu", "Termin Tarihi"],
        [[f"SIP-{i}", f"TSL-{i}", "KMB-24", 25, "64", "05.09.2026"] for i in range(4)],
    )
    istemci.post("/siparisler/yukle", files={"dosya": ("siparis.xlsx", siparis_dosyasi)})

    cevap = istemci.post(
        "/planlar/uret", data={"plan_tarihi": "2026-08-31", "depo_kodu": "64"}
    )
    assert "1 plan üretildi" in sorgu(cevap)

    planlar = istemci.get("/planlar")
    assert "2608D1001" in planlar.text

    detay = istemci.get("/planlar/1")
    assert detay.status_code == 200
    assert "2608D1001" in detay.text

    # Axata numarası girilmeden mail gönderilemez.
    cevap = istemci.post("/planlar/1/mail")
    assert "Axata" in sorgu(cevap)

    istemci.post("/planlar/1/axata", data={"axata_no": "AX-5501"})
    cevap = istemci.post("/planlar/1/mail")
    assert "hata=" not in sorgu(cevap)

    form = istemci.get("/planlar/1/form")
    assert form.status_code == 200
    assert form.headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )

    izleme = istemci.get("/izleme", params={"anahtar": "TSL-1"})
    assert "2608D1001" in izleme.text
