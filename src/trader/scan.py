"""Scan do universo: filtros duros determinísticos -> features -> score por categoria. Nada de texto externo sai daqui."""
import json
import time
from datetime import datetime, timedelta, timezone

import httpx

from trader import indicators as ind
from trader.config import valid_symbol
from trader.db import now_iso

TAGS_URL = "https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products"
DAY_MS = 86_400_000


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------- cache de idade de listagem e tags ----------

def refresh_tags(conn, fetch=None) -> bool:
    """Tags (Seed/Monitoring) vêm de endpoint NÃO oficial: cache de 24h; falha = mantém cache antigo."""
    row = conn.execute("SELECT MAX(updated_at) m FROM listings WHERE tags IS NOT NULL").fetchone()
    if row["m"] and datetime.fromisoformat(row["m"]) > datetime.now(timezone.utc) - timedelta(hours=24):
        return True
    try:
        data = (fetch or (lambda: httpx.get(TAGS_URL, timeout=15).json()))()["data"]
    except Exception:
        return row["m"] is not None
    for p in data:
        sym = f"{p.get('b')}/{p.get('q')}"
        if p.get("q") != "USDT" or not valid_symbol(sym):
            continue
        tags = [t for t in (p.get("tags") or []) if isinstance(t, str) and t.isalnum()][:20]
        conn.execute("INSERT INTO listings(symbol, tags, updated_at) VALUES(?,?,?) "
                     "ON CONFLICT(symbol) DO UPDATE SET tags=excluded.tags, updated_at=excluded.updated_at",
                     (sym, json.dumps(tags), now_iso()))
    return True


def listing_age_days(conn, ex, symbol: str) -> float | None:
    row = conn.execute("SELECT first_candle_ms FROM listings WHERE symbol=?", (symbol,)).fetchone()
    first = row["first_candle_ms"] if row else None
    if first is None:
        c = ex.ohlcv(symbol, "1d", 1, since=0)
        if not c:
            return None
        first = int(c[0][0])
        conn.execute("INSERT INTO listings(symbol, first_candle_ms, updated_at) VALUES(?,?,?) "
                     "ON CONFLICT(symbol) DO UPDATE SET first_candle_ms=excluded.first_candle_ms",
                     (symbol, first, now_iso()))
    return (time.time() * 1000 - first) / DAY_MS


def _tags(conn, symbol) -> list | None:
    row = conn.execute("SELECT tags FROM listings WHERE symbol=?", (symbol,)).fetchone()
    return json.loads(row["tags"]) if row and row["tags"] else None


# ---------- filtros duros ----------

def hard_filter(ex, conn, cfg, tickers: dict) -> tuple[list[dict], dict]:
    u = cfg.universe
    f = u["filters"]
    tags_ok = refresh_tags(conn)
    kept, dropped = [], {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for sym in ex.symbols():
        r = ex.rules(sym)
        t = tickers.get(sym)
        if not valid_symbol(sym) or r.base in u["blacklist"]:
            drop("blacklist"); continue
        if not t or not t.get("last") or not t.get("bid") or not t.get("ask"):
            drop("sem_ticker"); continue
        if (t.get("quoteVolume") or 0) < f["min_quote_volume_24h"]:
            drop("volume"); continue
        spread = (t["ask"] - t["bid"]) / t["ask"] * 100
        if spread > f["max_spread_pct"]:
            drop("spread"); continue
        if float(r.tick) / t["last"] * 100 > f["max_tick_pct"]:
            drop("tick"); continue
        cat = cfg.category(sym)
        tags = _tags(conn, sym)
        if tags and set(tags) & set(f["block_tags"]):
            drop("tag"); continue
        age = listing_age_days(conn, ex, sym)
        min_age = f["min_listing_days"][cat]
        if not tags_ok and cat != "major":   # sem tags: conservador
            min_age = max(min_age, 90)
        if age is None or age < min_age:
            drop("idade"); continue
        kept.append({"symbol": sym, "category": cat, "last": t["last"], "quote_volume": t["quoteVolume"],
                     "change_24h": t.get("percentage") or 0.0, "spread_pct": round(spread, 3),
                     "age_days": int(age), "tags": tags or []})
    return kept, dropped


# ---------- features e score ----------

def features(c1h: list, c4h: list) -> dict | None:
    if len(c1h) < 60 or len(c4h) < 60:
        return None
    cl1, cl4 = [c[4] for c in c1h], [c[4] for c in c4h]
    p = cl1[-1]
    # A última vela do ccxt é a que ainda está se formando: sinais usam só velas FECHADAS.
    closed4, cl4c = c4h[:-1], cl4[:-1]
    vols = [c[5] for c in c1h[:-1]]
    base_vol = sum(vols[-25:-1]) / 24 or 1e-12
    e20_4, e50_4 = ind.ema(cl4c, 20)[-1], ind.ema(cl4c, 50)[-1]
    e20_1 = ind.ema(cl1[:-1], 20)[-1]
    don = ind.donchian_high(closed4, 20)
    a1, a4 = ind.atr(c1h[:-1]), ind.atr(closed4)
    hi_30d = max(c[2] for c in c4h[-180:])
    return {
        "price": p,
        "vol_spike_1h": round(vols[-1] / base_vol, 2),
        "ret_1h": round(ind.pct_change(cl1[-2], p), 2),
        "ret_4h": round(ind.pct_change(cl1[-5], p), 2),
        "ret_24h": round(ind.pct_change(cl1[-25], p), 2),
        "rsi_1h": round(ind.rsi(cl1), 1),
        "rsi_4h": round(ind.rsi(cl4c), 1),
        "atr_1h": a1, "atr_4h": a4,
        "atr_1h_pct": round(a1 / p * 100, 2), "atr_4h_pct": round(a4 / p * 100, 2),
        "dist_high_30d_pct": round(ind.pct_change(hi_30d, p), 2),
        "above_ema20_1h": p > e20_1,
        "above_ema20_4h": p > e20_4,
        "ema20_gt_ema50_4h": e20_4 > e50_4,
        "donchian20_4h": don,
        "breakout_4h": cl4c[-1] > don,   # fechamento 4h confirmado acima da máxima de 20 velas
        "dist_donchian_pct": round(ind.pct_change(don, p), 2),
    }


def score(f: dict, w: dict) -> float:
    trend = 0.5 * f["above_ema20_4h"] + 0.5 * f["ema20_gt_ema50_4h"]
    breakout = 1.0 if f["breakout_4h"] else _clamp(1 + f["dist_donchian_pct"] / 5)
    momentum = _clamp((f["ret_4h"] / 5 + f["ret_24h"] / 15) / 2)
    volume = _clamp((f["vol_spike_1h"] - 1) / 4)
    s = w["trend"] * trend + w["breakout"] * breakout + w["momentum"] * momentum + w["volume"] * volume
    if f["rsi_1h"] > 80:   # esticado demais
        s *= 0.7
    return round(s, 3)


def _prescore(c: dict) -> float:
    return c["quote_volume"] ** 0.5 * (1 + abs(c["change_24h"]) / 10)


def scan(ex, conn, cfg) -> dict:
    """Retorna TODOS os finalistas com features (a sombra usa todos; a tool corta no top_n)."""
    tickers = ex.tickers()
    kept, dropped = hard_filter(ex, conn, cfg, tickers)
    n = cfg.universe["scan"]["finalists"]
    majors = [c for c in kept if c["category"] == "major"]
    others = sorted((c for c in kept if c["category"] != "major"), key=_prescore, reverse=True)
    finalists = (majors + others)[:max(n, len(majors))]
    out = []
    for c in finalists:
        f = features(ex.ohlcv(c["symbol"], "1h", 120), ex.ohlcv(c["symbol"], "4h", 200))
        if f is None:
            continue
        c.update(f)
        c["score"] = score(f, cfg.universe["scan"]["weights"][c["category"]])
        out.append(c)
    out.sort(key=lambda c: c["score"], reverse=True)
    return {"passed_filters": len(kept), "dropped": dropped, "candidates": out}


def compact(c: dict) -> dict:
    """Versão enxuta para o contexto do Claude."""
    keys = ("symbol", "category", "score", "price", "vol_spike_1h", "ret_1h", "ret_4h", "ret_24h", "rsi_1h", "rsi_4h",
            "atr_1h_pct", "atr_4h_pct", "dist_high_30d_pct", "above_ema20_1h", "above_ema20_4h", "ema20_gt_ema50_4h",
            "breakout_4h", "dist_donchian_pct", "spread_pct", "age_days", "tags")
    return {k: c[k] for k in keys if k in c}
