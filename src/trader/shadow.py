"""Estratégia sombra: regras fixas, sem LLM, sem ordem. Mesmo risk manager e mesmo scan do agente,
para medir se o Claude agrega valor. Fills simulados com taxa + slippage.
"""
from datetime import datetime, timedelta, timezone

from trader import risk
from trader.db import get_state, insert, now_iso, set_state, update
from trader.exchange import D


def signal(c: dict):
    """(setup, horizon, stop, target, horas_para_saida_por_tempo) ou None."""
    p = c["price"]
    if c["category"] in ("major", "alt") and c["breakout_4h"] and c["ema20_gt_ema50_4h"]:
        stop = p - 2 * c["atr_4h"]                       # freqtrade FixedRiskRewardLoss: 2 ATR, alvo 3,5R
        return "swing_breakout_4h", "swing", stop, p + 3.5 * (p - stop), None
    if c["vol_spike_1h"] >= 3 and c["ret_1h"] > 0 and c["rsi_1h"] < 80:
        stop = p - 1.5 * c["atr_1h"]
        setup = "meme_momentum" if c["category"] == "meme" else "intraday_momentum_1h"
        return setup, "intraday", stop, p + 2 * (p - stop), 24
    return None


def _state(conn, cfg, regime: str, now: datetime, start_equity) -> risk.RiskState:
    closed = conn.execute("SELECT COALESCE(SUM(pnl_usd),0) s FROM shadow_trades WHERE status='closed'").fetchone()["s"]
    equity = D(start_equity) + D(closed)
    opens = conn.execute("SELECT * FROM shadow_trades WHERE status='open'").fetchall()
    positions = [risk.Position(o["symbol"], o["category"], D(o["qty"]) * D(o["entry_price"])) for o in opens]
    ds = risk.day_start(now, cfg["timezone"]).astimezone(timezone.utc).isoformat(timespec="seconds")
    today = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(qty*entry_price),0) v FROM shadow_trades WHERE opened_at>=?",
                         (ds,)).fetchone()
    realized = conn.execute("SELECT COALESCE(SUM(pnl_usd),0) s FROM shadow_trades WHERE status='closed' AND closed_at>=?",
                            (ds,)).fetchone()["s"]
    since = (now - timedelta(hours=48)).isoformat(timespec="seconds")
    stops = conn.execute("SELECT symbol, closed_at FROM shadow_trades WHERE exit_reason='stop' AND closed_at>=?",
                         (since,)).fetchall()
    return risk.RiskState(
        equity_usd=equity, free_usdt=equity - sum((p.value_usd for p in positions), D(0)),
        day_start_equity=equity - D(realized), realized_today=D(realized), trades_today=today["n"],
        notional_today=D(today["v"]), positions=positions,
        last_stop_at={s["symbol"]: datetime.fromisoformat(s["closed_at"]) for s in stops},
        recent_stops=[datetime.fromisoformat(s["closed_at"]) for s in stops], regime=regime)


def _close(conn, o, exit_price, reason, fee, slip):
    exit_net = exit_price * (1 - slip) if reason != "target" else exit_price   # alvo é limite: sem slippage
    pnl = o["qty"] * (exit_net * (1 - fee) - o["entry_price"] * (1 + fee))
    r = pnl / (o["qty"] * (o["entry_price"] - o["stop_price"]))
    update(conn, "shadow_trades", o["id"], {"status": "closed", "closed_at": now_iso(), "exit_price": exit_net,
                                            "exit_reason": reason, "pnl_usd": pnl, "r_multiple": r})


def step(conn, ex, cfg, candidates: list[dict], regime: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rc = cfg.risk
    fee = rc["fee_pct"] / 100
    closed = opened = 0
    # 1. fecha posições da sombra olhando as velas 1h desde a abertura (stop primeiro = conservador)
    for o in conn.execute("SELECT * FROM shadow_trades WHERE status='open'").fetchall():
        slip = rc["slippage_pct"][o["category"]] / 100
        since = int(datetime.fromisoformat(o["opened_at"]).timestamp() * 1000)
        candles = ex.ohlcv(o["symbol"], "1h", 200, since=since)
        for c in candles[1:]:   # a vela da entrada não conta
            if c[3] <= o["stop_price"]:
                _close(conn, o, min(o["stop_price"], c[1]), "stop", fee, slip); closed += 1; break
            if c[2] >= o["target_price"]:
                _close(conn, o, o["target_price"], "target", fee, slip); closed += 1; break
        else:
            if o["time_exit_at"] and now >= datetime.fromisoformat(o["time_exit_at"]) and candles:
                _close(conn, o, candles[-1][4], "time", fee, slip); closed += 1
    # 2. abre o que as regras mandam, passando pelo MESMO risk manager
    start = get_state(conn, "shadow_start_equity")
    if start is None:
        last = conn.execute("SELECT equity_usd FROM equity_history ORDER BY ts DESC LIMIT 1").fetchone()
        start = last["equity_usd"] if last else 100.0
        set_state(conn, "shadow_start_equity", start)
    for c in candidates:
        sig = signal(c)
        if not sig:
            continue
        setup, horizon, stop, target, hours = sig
        st = _state(conn, rc, regime, now, start)
        rules = ex.rules(c["symbol"])
        a = c["atr_4h"] if horizon == "swing" else c["atr_1h"]
        d = risk.check_entry({**rc, "mode": "live"}, st, rules, category=c["category"], ask=c["price"],
                             stop=stop, target=target, atr=a, now=now)
        if not d.ok:
            continue
        insert(conn, "shadow_trades", {
            "symbol": c["symbol"], "category": c["category"], "setup": setup, "status": "open",
            "opened_at": now.isoformat(timespec="seconds"), "entry_price": float(d.limit_price), "qty": float(d.qty),
            "stop_price": float(d.stop), "target_price": float(d.target),
            "time_exit_at": (now + timedelta(hours=hours)).isoformat(timespec="seconds") if hours else None})
        opened += 1
    return {"shadow_opened": opened, "shadow_closed": closed}
