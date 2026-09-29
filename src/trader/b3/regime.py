"""Regime do WIN no diário e no 60m: alta | baixa | lateral (EMA20 x EMA50 + fechamento) e volatilidade relativa."""
from trader.b3.features import atr, f
from trader.broker.base import Bar
from trader.indicators import ema


def trend(bars: list[Bar]) -> str | None:
    closes = [f(b.close) for b in bars]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    if not e50:
        return None
    last, a, b = closes[-1], e20[-1], e50[-1]
    if a > b and last > a:
        return "alta"
    if a < b and last < a:
        return "baixa"
    return "lateral"


def regime(daily: list[Bar], h60: list[Bar]) -> dict:
    a14, a50 = atr(daily, 14), atr(daily, 50)
    vol = round(a14 / a50, 2) if a14 and a50 else None
    return {"daily": trend(daily), "h60": trend(h60), "vol_rel": vol,
            "vol": None if vol is None else ("alta" if vol > 1.2 else "baixa" if vol < 0.8 else "normal")}
