"""Fluxo: agressão compradora/vendedora (ticks com flag) e desequilíbrio de book. Sem dado = 'indisponível'."""
from datetime import datetime, timedelta

from trader.broker.base import Tick

NA = {"status": "indisponível"}


def aggression(ticks: list[Tick], since: datetime | None = None) -> dict:
    sel = [t for t in ticks if since is None or t.time >= since]
    flagged = [t for t in sel if t.aggressor]
    if not flagged:
        return dict(NA)
    buy = float(sum(t.volume for t in flagged if t.aggressor == "long"))
    sell = float(sum(t.volume for t in flagged if t.aggressor == "short"))
    tot = buy + sell
    return {"buy": buy, "sell": sell, "delta": buy - sell, "buy_ratio": round(buy / tot, 3) if tot else None,
            "coverage": round(len(flagged) / len(sel), 3)}


def aggression_windows(ticks: list[Tick], now: datetime, windows_min=(5, 15, 60)) -> dict:
    out = {f"{w}m": aggression(ticks, now - timedelta(minutes=w)) for w in windows_min}
    out["day"] = aggression([t for t in ticks if t.time.date() == now.date()])
    return out


def book_imbalance(book: dict | None, depth: int = 5) -> dict:
    if not book or not book.get("bids") or not book.get("asks"):
        return dict(NA)
    b = float(sum(v for _, v in book["bids"][:depth]))
    a = float(sum(v for _, v in book["asks"][:depth]))
    return {"bid_volume": b, "ask_volume": a, "imbalance": round((b - a) / (b + a), 3) if b + a else None,
            "depth": depth}
