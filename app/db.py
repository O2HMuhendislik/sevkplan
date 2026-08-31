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


def semayi_olustur() -> None:
    from app import models  # noqa: F401  (tabloların kaydolması için)

    models.Temel.metadata.create_all(motor)


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
