"""Sevkiyat takvimi: hangi günlere plan üretilebilir.

Sevkiyat **pazar günleri yapılmaz**; diğer bütün günler çalışma günüdür (cumartesi
dahil — depo cumartesi de yüklüyor). Resmî tatiller burada tanımlı değil: tatil
takvimi her yıl değiştiği için sahadan gelmeden varsayım yapılmıyor, o günlere düşen
planı kullanıcı elle taşır.
"""
from __future__ import annotations

from datetime import date, timedelta

PAZAR = 6
"""`date.weekday()` numarası; pazartesi 0, pazar 6."""


def calisma_gunu_mu(gun: date) -> bool:
    return gun.weekday() != PAZAR


def calisma_gunune_al(gun: date) -> date:
    """Verilen gün pazara denk geliyorsa ertesi güne (pazartesi) taşır."""
    return gun + timedelta(days=1) if not calisma_gunu_mu(gun) else gun


def sonraki_calisma_gunu(gun: date) -> date:
    """Bir sonraki çalışma günü; pazar atlanır."""
    return calisma_gunune_al(gun + timedelta(days=1))
