"""Features do WIN: funções puras sobre barras (base.Bar, horário de Brasília).

Níveis conhecidos (LEVEL_REFS) são as únicas referências que o plano do dia pode usar, além de preço absoluto.
"""
import math
from datetime import date, datetime, timedelta

from trader.broker.base import Bar
from trader.broker.sim import resample
from trader.indicators import atr as _atr

LEVEL_REFS = ("vwap", "vwap_up1", "vwap_dn1", "vwap_up2", "vwap_dn2", "or15_high", "or15_low", "or30_high",
              "or30_low", "pdh", "pdl", "pdc", "day_open", "day_high", "day_low")


def f(x) -> float:
    return float(x)


def day_bars(bars: list[Bar], day: date) -> list[Bar]:
    return [b for b in bars if b.time.date() == day]


def atr(bars: list[Bar], n: int = 14) -> float | None:
    return _atr([[0, f(b.open), f(b.high), f(b.low), f(b.close), f(b.volume)] for b in bars], n)


def vwap_bands(bars: list[Bar]) -> dict | None:
    """VWAP do dia pelo preço típico e desvio-padrão ponderado por volume."""
    vol = sum(f(b.volume) for b in bars)
    if not bars or vol <= 0:
        return None
    tp = [(f(b.high) + f(b.low) + f(b.close)) / 3 for b in bars]
    vw = sum(p * f(b.volume) for p, b in zip(tp, bars)) / vol
    sd = math.sqrt(sum(f(b.volume) * (p - vw) ** 2 for p, b in zip(tp, bars)) / vol)
    return {"vwap": vw, "vwap_up1": vw + sd, "vwap_dn1": vw - sd, "vwap_up2": vw + 2 * sd, "vwap_dn2": vw - 2 * sd,
            "vwap_sd": sd}


def opening_range(today_1m: list[Bar], minutes: int) -> tuple[float, float] | None:
    """(máxima, mínima) dos primeiros `minutes` do pregão; None enquanto a janela não fechou."""
    if not today_1m:
        return None
    end = today_1m[0].time + timedelta(minutes=minutes)
    inside = [b for b in today_1m if b.time < end]
    if today_1m[-1].time + timedelta(minutes=1) < end:
        return None
    return max(f(b.high) for b in inside), min(f(b.low) for b in inside)


def prior_day(daily: list[Bar], today: date) -> dict | None:
    prev = [b for b in daily if b.time.date() < today]
    if not prev:
        return None
    p = prev[-1]
    return {"pdh": f(p.high), "pdl": f(p.low), "pdc": f(p.close), "date": p.time.date().isoformat()}


def relative_volume(bars_1m: list[Bar], now: datetime, days: int = 10) -> float | None:
    """Volume do dia até agora / média dos últimos `days` pregões até o mesmo horário."""
    today = now.date()
    cut = now.time()
    cum = sum(f(b.volume) for b in day_bars(bars_1m, today) if b.time.time() < cut)
    prev_days = sorted({b.time.date() for b in bars_1m if b.time.date() < today})[-days:]
    hist = [sum(f(b.volume) for b in bars_1m if b.time.date() == d and b.time.time() < cut) for d in prev_days]
    hist = [h for h in hist if h > 0]
    if not hist or not cum:
        return None
    return cum / (sum(hist) / len(hist))


def levels(bars_1m: list[Bar], daily: list[Bar], today: date) -> dict:
    """Todos os níveis conhecidos disponíveis agora (os que ainda não existem ficam de fora)."""
    tb = day_bars(bars_1m, today)
    out = {}
    if tb:
        out.update(day_open=f(tb[0].open), day_high=max(f(b.high) for b in tb), day_low=min(f(b.low) for b in tb))
        vb = vwap_bands(tb)
        if vb:
            out.update({k: v for k, v in vb.items() if k in LEVEL_REFS})
        for m in (15, 30):
            orr = opening_range(tb, m)
            if orr:
                out[f"or{m}_high"], out[f"or{m}_low"] = orr
    pd = prior_day(daily, today)
    if pd:
        out.update(pdh=pd["pdh"], pdl=pd["pdl"], pdc=pd["pdc"])
    return out


def snapshot(bars_1m: list[Bar], daily: list[Bar], now: datetime, tick: float = 5) -> dict:
    """Resumo compacto para o operador e os analistas (nada de velas cruas)."""
    today = now.date()
    tb = day_bars(bars_1m, today)
    b5 = resample(tb, 5)
    lv = levels(bars_1m, daily, today)
    a5, a15, ad = atr(resample(bars_1m, 5)), atr(resample(bars_1m, 15)), atr(daily)
    last = f(tb[-1].close) if tb else (f(bars_1m[-1].close) if bars_1m else None)
    pd = prior_day(daily, today)
    out = {"now": now.isoformat(timespec="minutes"), "last": last,
           "atr_5m": round(a5, 1) if a5 else None, "atr_15m": round(a15, 1) if a15 else None,
           "atr_daily": round(ad, 1) if ad else None, "relative_volume": relative_volume(bars_1m, now),
           "levels": {k: round(v, 1) for k, v in lv.items()}, "bars_5m_today": len(b5)}
    if tb and pd:
        gap = f(tb[0].open) - pd["pdc"]
        out["gap"] = {"points": round(gap, 1), "atr_daily": round(gap / ad, 2) if ad else None}
    if last is not None:
        out["distance"] = {k: {"ticks": round((v - last) / tick), "atr5m": round((v - last) / a5, 2) if a5 else None}
                           for k, v in lv.items()}
    return out
