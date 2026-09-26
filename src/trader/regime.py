"""Regime de mercado pelo BTC: EMA20/50 em 1h e 4h + volatilidade (ATR% 4h)."""
from trader.indicators import atr, ema


def _trend(candles) -> str:
    closes = [c[4] for c in candles]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    if not e50:
        return "?"
    p = closes[-1]
    if p > e20[-1] > e50[-1]:
        return "up"
    if p < e20[-1] < e50[-1]:
        return "down"
    return "flat"


def classify(c1h: list, c4h: list) -> dict:
    t1, t4 = _trend(c1h), _trend(c4h)
    if "?" in (t1, t4):
        regime = "BEAR"   # sem dado suficiente = conservador
    elif t4 == "up" and t1 != "down":
        regime = "BULL"
    elif t4 == "down" and t1 != "up":
        regime = "BEAR"
    else:
        regime = "NEUTRO"
    a = atr(c4h)
    atr_pct = round(a / c4h[-1][4] * 100, 2) if a else None
    return {"regime": regime, "btc_trend_1h": t1, "btc_trend_4h": t4, "btc_atr4h_pct": atr_pct,
            "btc_price": c4h[-1][4] if c4h else None}


def get_regime(ex) -> dict:
    return classify(ex.ohlcv("BTC/USDT", "1h", 120), ex.ohlcv("BTC/USDT", "4h", 120))
