"""Veritabanı oturum yönetimi."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import VERITABANI_URL

motor = create_engine(
    VERITABANI_URL,
    future=True,
    connect_args={"check_same_thread": False} if VERITABANI_URL.startswith("sqlite") else {},
)


@event.listens_for(motor, "connect")
def _sqlite_ayarlari(dbapi_baglanti, _kayit) -> None:
    """SQLite'ta yabancı anahtar kısıtları varsayılan olarak kapalıdır."""
    if VERITABANI_URL.startswith("sqlite"):
        imlec = dbapi_baglanti.cursor()
        imlec.execute("PRAGMA foreign_keys=ON")
        imlec.close()


OturumFabrikasi = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


class SemaUyumsuzlugu(RuntimeError):
    """Mevcut veritabanı yeni sürümle otomatik uyumlu hale getirilemiyor."""


def semayi_olustur() -> None:
    """Tabloları oluşturur ve mevcut veritabanını yeni sürüme uyarlar.

    Program güncellendiğinde eski `sevkplan.db` dosyası genellikle olduğu gibi
    kullanılmaya devam eder: yeni eklenen kolonlar otomatik eklenir. Otomatik
    çözülemeyen bir fark varsa anlaşılır bir hata mesajı verilir.
    """
    from app import models  # noqa: F401  (tabloların kaydolması için)

    models.Temel.metadata.create_all(motor)
    _eksik_kolonlari_ekle()
    _uyumsuzluk_kontrolu()


def _mevcut_kolonlar(denetci, tablo: str) -> dict[str, dict]:
    return {kolon["name"]: kolon for kolon in denetci.get_columns(tablo)}


def _eksik_kolonlari_ekle() -> None:
    """Yeni sürümde eklenen kolonları mevcut tablolara ekler."""
    from sqlalchemy import inspect, text

    from app import models

    denetci = inspect(motor)
    mevcut_tablolar = set(denetci.get_table_names())
    with motor.begin() as baglanti:
        for tablo in models.Temel.metadata.sorted_tables:
            if tablo.name not in mevcut_tablolar:
                continue
            var_olanlar = _mevcut_kolonlar(denetci, tablo.name)
            for kolon in tablo.columns:
                if kolon.name in var_olanlar:
                    continue
                tanim = f"{kolon.name} {kolon.type.compile(motor.dialect)}"
                if kolon.default is not None and kolon.default.is_scalar:
                    deger = kolon.default.arg
                    if isinstance(deger, bool):
                        deger = int(deger)
                    tanim += (
                        f" DEFAULT {deger!r}" if isinstance(deger, str)
                        else f" DEFAULT {deger}"
                    )
                baglanti.execute(
                    text(f"ALTER TABLE {tablo.name} ADD COLUMN {tanim}")
                )


def _uyumsuzluk_kontrolu() -> None:
    """Otomatik düzeltilemeyen kalıntıları tespit eder.

    Eski sürümden kalan ve artık kullanılmayan bir kolon NOT NULL ise, yeni kayıtlar
    eklenemez. Bu durumda veritabanının sıfırlanması gerekir.
    """
    from sqlalchemy import inspect

    from app import models

    denetci = inspect(motor)
    mevcut_tablolar = set(denetci.get_table_names())
    sorunlular: list[str] = []
    for tablo in models.Temel.metadata.sorted_tables:
        if tablo.name not in mevcut_tablolar:
            continue
        model_kolonlari = {kolon.name for kolon in tablo.columns}
        for ad, kolon in _mevcut_kolonlar(denetci, tablo.name).items():
            if ad in model_kolonlari:
                continue
            if not kolon["nullable"] and kolon.get("default") is None:
                sorunlular.append(f"{tablo.name}.{ad}")
    if sorunlular:
        raise SemaUyumsuzlugu(
            "Mevcut veritabanı programın bu sürümüyle uyumlu değil "
            f"(eski kolonlar: {', '.join(sorunlular)}).\n"
            "Çözüm: 'python -m scripts.veritabani_sifirla' komutunu çalıştırın. "
            "Komut mevcut dosyayı yedekler, boş bir veritabanı oluşturur; "
            "ardından master data ve sipariş dosyalarını yeniden yükleyin."
        )


@contextmanager
def oturum() -> Iterator[Session]:
    db = OturumFabrikasi()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def oturum_bagimliligi() -> Iterator[Session]:
    """FastAPI Depends için oturum sağlayıcı."""
    db = OturumFabrikasi()
    try:
        yield db
    finally:
        db.close()
