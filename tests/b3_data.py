"""Barras sintéticas do WIN (1m, horário de Brasília) para testes."""
from datetime import date, datetime, timedelta
from decimal import Decimal as Dec
from zoneinfo import ZoneInfo

from trader.broker.base import Bar

TZ = ZoneInfo("America/Sao_Paulo")


def day(d: date, path: list[float], start="09:00", vol=100, wick=10) -> list[Bar]:
    """Uma barra 1m por preço de `path` (fechamento), abrindo no fechamento anterior."""
    t = datetime.combine(d, datetime.strptime(start, "%H:%M").time(), TZ)
    out, prev = [], path[0]
    for i, c in enumerate(path):
        o = prev
        out.append(Bar(t + timedelta(minutes=i), Dec(str(o)), Dec(str(max(o, c) + wick)), Dec(str(min(o, c) - wick)),
                       Dec(str(c)), Dec(vol)))
        prev = c
    return out


def ramp(a: float, b: float, n: int) -> list[float]:
    """n preços de a até b, arredondados ao tick de 5."""
    return [round((a + (b - a) * i / max(n - 1, 1)) / 5) * 5 for i in range(n)]


def daily(end: date, n: int, start=120000.0, step=100.0) -> list[Bar]:
    out, p = [], start
    d = end - timedelta(days=n)
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(Bar(datetime.combine(d, datetime.min.time(), TZ), Dec(str(p)), Dec(str(p + 800)),
                           Dec(str(p - 700)), Dec(str(p + step)), Dec(100000)))
            p += step
    return out
