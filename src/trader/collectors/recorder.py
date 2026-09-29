"""Grava barras 1m, ticks (com agressão) e book do WIN no SQLite: base para backtest e análise depois."""
import json
from datetime import datetime, timedelta
from decimal import Decimal

from trader.broker.base import Bar, BrokerError
from trader.db import now_iso
from trader.trading_b3 import TZ


def record(conn, broker, symbol: str, now: datetime, book: bool = True) -> dict:
    out = {"bars": 0, "ticks": 0, "book": False}
    bars = broker.bars(symbol, "1m", 600)[:-1]           # a última está em formação
    conn.executemany("INSERT OR REPLACE INTO b3_bars VALUES (?,?,?,?,?,?,?,?)",
                     [(symbol, "1m", b.time.isoformat(), float(b.open), float(b.high), float(b.low),
                       float(b.close), float(b.volume)) for b in bars])
    out["bars"] = len(bars)
    last = conn.execute("SELECT MAX(time) t FROM b3_ticks WHERE symbol=?", (symbol,)).fetchone()["t"]
    since = datetime.fromisoformat(last) if last else now - timedelta(minutes=10)
    ticks = [t for t in broker.ticks(symbol, since) if last is None or t.time.isoformat() > last]
    conn.executemany("INSERT INTO b3_ticks VALUES (?,?,?,?,?,?,?)",
                     [(symbol, t.time.isoformat(), float(t.bid), float(t.ask), float(t.last), float(t.volume),
                       t.aggressor) for t in ticks])
    out["ticks"] = len(ticks)
    if book:
        try:
            bk = broker.book(symbol)
        except BrokerError:
            bk = None
        if bk:
            conn.execute("INSERT INTO b3_book VALUES (?,?,?)", (symbol, now_iso(), json.dumps(bk, default=float)))
            out["book"] = True
    return out


def load_bars(conn, symbol: str, since: datetime | None = None) -> list[Bar]:
    q, args = "SELECT * FROM b3_bars WHERE symbol=? AND tf='1m'", [symbol]
    if since:
        q += " AND time>=?"
        args.append(since.isoformat())
    return [Bar(datetime.fromisoformat(r["time"]).astimezone(TZ), Decimal(str(r["open"])), Decimal(str(r["high"])),
                Decimal(str(r["low"])), Decimal(str(r["close"])), Decimal(str(r["volume"])))
            for r in conn.execute(q + " ORDER BY time", args)]
