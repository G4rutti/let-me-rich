"""Indicadores em Python puro. Candles no formato ccxt: [ts, open, high, low, close, volume]."""


def ema(values: list[float], n: int) -> list[float]:
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], n: int = 14) -> float | None:
    """RSI de Wilder, último valor."""
    if len(closes) <= n:
        return None
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:])]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:])]
    avg_g, avg_l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def atr(candles: list[list[float]], n: int = 14) -> float | None:
    """ATR de Wilder, último valor."""
    if len(candles) <= n:
        return None
    trs = [max(c[2] - c[3], abs(c[2] - p[4]), abs(c[3] - p[4])) for p, c in zip(candles, candles[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def donchian_high(candles: list[list[float]], n: int = 20) -> float | None:
    """Máxima das n velas ANTERIORES à última (rompimento = close atual acima disso)."""
    if len(candles) <= n:
        return None
    return max(c[2] for c in candles[-n - 1:-1])


def pct_change(a: float, b: float) -> float:
    return (b - a) / a * 100 if a else 0.0
