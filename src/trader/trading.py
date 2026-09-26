"""Operações de posição. Toda escrita na exchange passa por aqui, SEMPRE depois do risk manager.

Padrão de cada ordem: audit 'intent' (fsync) -> exchange -> audit 'result' | 'error'.
"""
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from trader import risk
from trader.db import get_state, insert, now_iso, set_state, update
from trader.exchange import D, ExchangeError, client_id
from trader.journal import audit, setup_stats

ACTIVE = ("NEW", "PARTIALLY_FILLED", "PENDING_NEW")


class TradeError(Exception):
    def __init__(self, code: str, hint: str):
        super().__init__(f"{code}: {hint}")
        self.code, self.hint = code, hint


@dataclass
class Ctx:
    conn: object
    ex: object
    cfg: object
    cycle_id: str = "manual"
    notify: Callable[[str], object] = print
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    sleep: Callable[[float], None] = time.sleep


def status_of(order: dict) -> str:
    return ((order.get("info") or {}).get("status") or order.get("status") or "").upper()


def trade(conn, trade_id: int) -> dict:
    row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not row:
        raise TradeError("NO_TRADE", f"trade {trade_id} não existe")
    return dict(row)


def fresh_open_trade(ctx, symbol: str) -> dict:
    """Reconcilia antes de mexer: o OCO pode ter executado desde o último sync."""
    from trader.sync import reconcile_trade
    reconcile_trade(ctx, open_trade_for(ctx.conn, symbol))
    return open_trade_for(ctx.conn, symbol)


def open_trade_for(conn, symbol: str) -> dict:
    row = conn.execute("SELECT * FROM trades WHERE symbol=? AND status='open' AND mode='live'", (symbol,)).fetchone()
    if not row:
        raise TradeError("NO_POSITION", f"sem posição aberta em {symbol}")
    return dict(row)


def active_trades(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE status IN ('pending','open') AND mode='live' ORDER BY id")]


def usd_value(ex, asset: str, amount) -> Decimal:
    if asset == "USDT" or not amount:
        return D(amount or 0)
    try:
        return D(amount) * D(ex.ticker(f"{asset}/USDT")["last"])
    except Exception:
        return D(0)


def usdt_brl(ex) -> float | None:
    try:
        return ex.ticker("USDT/BRL")["last"]
    except Exception:
        return None


def _order_ok(conn) -> None:
    set_state(conn, "consecutive_order_failures", 0)


def _order_failed(ctx: Ctx, what: str, err: Exception) -> None:
    n = get_state(ctx.conn, "consecutive_order_failures", 0) + 1
    set_state(ctx.conn, "consecutive_order_failures", n)
    if n >= ctx.cfg.risk["max_consecutive_order_failures"]:
        set_state(ctx.conn, "paused", True)
        ctx.notify(f"🛑 CIRCUIT BREAKER: {n} falhas de ordem seguidas ({what}: {err}). Bot pausado; /resume após revisar.")


def _send(ctx: Ctx, action: str, symbol: str, cid: str, fn, /, *args, **detail):
    """Envia uma ordem com audit intent/result. Levanta ExchangeError após registrar."""
    audit(ctx.conn, ctx.cycle_id, action, symbol, "intent", detail={"client_id": cid, **detail})
    try:
        res = fn(*args)
    except ExchangeError as e:
        audit(ctx.conn, ctx.cycle_id, action, symbol, "error", e.code, {"client_id": cid, "error": str(e)})
        _order_failed(ctx, action, e)
        raise
    audit(ctx.conn, ctx.cycle_id, action, symbol, "result", detail={"client_id": cid})
    _order_ok(ctx.conn)
    return res


# ---------------------------------------------------------------- estado de risco

def portfolio(ctx: Ctx) -> dict:
    ex, conn = ctx.ex, ctx.conn
    bal = ex.balance()
    usdt = bal.get("USDT", {"free": D(0), "locked": D(0)})
    positions = []
    for t in active_trades(conn):
        last = D(ex.ticker(t["symbol"])["last"])
        qty = D(t["qty"] if t["qty"] is not None else t["planned_qty"])
        value = qty * (last if t["status"] == "open" else D(t["entry_limit"]))
        pos = {"trade_id": t["id"], "symbol": t["symbol"], "category": t["category"], "setup": t["setup"],
               "horizon": t["horizon"], "status": t["status"], "qty": float(qty), "last": float(last),
               "value_usd": round(float(value), 2), "entry_price": t["entry_price"], "stop": t["stop_price"],
               "target": t["target_price"], "opened_at": t["opened_at"]}
        if t["status"] == "open" and t["entry_price"]:
            pos["unrealized_pct"] = round(float((last / D(t["entry_price"]) - 1) * 100), 2)
            pos["r_now"] = round(float((last - D(t["entry_price"])) * qty / D(t["risk_usd"])), 2) if t["risk_usd"] else None
        positions.append(pos)
    equity = usdt["free"] + usdt["locked"] + sum((D(p["value_usd"]) for p in positions), D(0))
    by_cat = {}
    for p in positions:
        by_cat[p["category"]] = round(by_cat.get(p["category"], 0) + p["value_usd"] / float(equity) * 100, 1) if equity else 0
    return {"equity_usd": round(float(equity), 2), "free_usdt": round(float(usdt["free"]), 2),
            "exposure_pct_by_category": by_cat, "positions": positions,
            "bnb_for_fees": float(bal.get("BNB", {}).get("free", 0))}


def risk_state(ctx: Ctx, pf: dict, regime: str, setup: str | None) -> risk.RiskState:
    conn, cfg, now = ctx.conn, ctx.cfg.risk, ctx.now()
    ds = risk.day_start(now, cfg["timezone"]).astimezone(timezone.utc).isoformat(timespec="seconds")
    first = conn.execute("SELECT equity_usd FROM equity_history WHERE ts>=? ORDER BY ts LIMIT 1", (ds,)).fetchone()
    equity = D(pf["equity_usd"])
    realized = conn.execute("SELECT COALESCE(SUM(pnl_usd),0) s FROM trades WHERE status='closed' AND closed_at>=?",
                            (ds,)).fetchone()["s"]
    today = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(entry_limit*planned_qty),0) v FROM trades "
                         "WHERE mode='live' AND created_at>=? AND status!='cancelled'", (ds,)).fetchone()
    since = (now - timedelta(hours=48)).isoformat(timespec="seconds")
    stops = conn.execute("SELECT symbol, closed_at FROM trades WHERE exit_reason='stop' AND closed_at>=?", (since,)).fetchall()
    last_stop = {}
    for s in stops:
        t = datetime.fromisoformat(s["closed_at"])
        last_stop[s["symbol"]] = max(t, last_stop.get(s["symbol"], t))
    status = "NEUTRO"
    if setup:
        st = setup_stats(conn, cfg["setup_stats"], setup).get(setup)
        status = st["status"] if st else "NEUTRO"
    return risk.RiskState(
        equity_usd=equity, free_usdt=D(pf["free_usdt"]),
        day_start_equity=D(first["equity_usd"]) if first else equity,
        realized_today=D(realized), trades_today=today["n"], notional_today=D(today["v"]),
        positions=[risk.Position(p["symbol"], p["category"], D(p["value_usd"])) for p in pf["positions"]],
        last_stop_at=last_stop, recent_stops=[datetime.fromisoformat(s["closed_at"]) for s in stops],
        consecutive_order_failures=get_state(conn, "consecutive_order_failures", 0),
        paused=bool(get_state(conn, "paused", False)), regime=regime, setup_status=status)


# ---------------------------------------------------------------- entrada

def place_entry(ctx: Ctx, *, symbol, horizon, setup, stop, target, reason, regime: str) -> dict:
    ex, conn, cfg = ctx.ex, ctx.conn, ctx.cfg
    list_id = client_id(ctx.cycle_id, symbol, "entry")
    existing = conn.execute("SELECT id, status FROM trades WHERE entry_list_id=?", (list_id,)).fetchone()
    if existing:   # retry no mesmo ciclo: devolve a ordem já enviada, não manda outra
        return {"trade_id": existing["id"], "status": f"já enviada neste ciclo ({existing['status']})"}
    rules = ex.rules(symbol)
    category = cfg.category(symbol)
    ticker = ex.ticker(symbol)
    tf = "4h" if horizon == "swing" else "1h"
    from trader.indicators import atr
    a = atr(ex.ohlcv(symbol, tf, 60))
    pf = portfolio(ctx)
    st = risk_state(ctx, pf, regime, setup)
    decision = risk.check_entry(cfg.risk, st, rules, category=category, ask=ticker["ask"], stop=stop,
                                target=target, atr=a, now=ctx.now())
    detail = {"setup": setup, "horizon": horizon, "stop": stop, "target": target, "ask": ticker["ask"], "atr": a}
    if not decision.ok:
        audit(conn, ctx.cycle_id, "place_entry", symbol, "rejected", decision.code, {**detail, "hint": decision.hint})
        raise TradeError(decision.code, decision.hint)
    plan = {"symbol": symbol, "category": category, "qty": str(decision.qty), "limit": str(decision.limit_price),
            "stop": str(decision.stop), "target": str(decision.target),
            "notional_usd": round(float(decision.notional), 2), "risk_usd": round(float(decision.risk_usd), 3)}
    audit(conn, ctx.cycle_id, "place_entry", symbol, "approved", detail={**detail, **plan})
    if cfg.risk["mode"] != "live":
        return {"dry_run": True, **plan}
    trade_id = insert(conn, "trades", {
        "mode": "live", "symbol": symbol, "category": category, "setup": setup, "horizon": horizon,
        "status": "pending", "entry_list_id": list_id, "protect_list_id": list_id,
        "entry_limit": float(decision.limit_price), "planned_qty": float(decision.qty),
        "initial_stop": float(decision.stop), "stop_price": float(decision.stop),
        "target_price": float(decision.target), "risk_usd": float(decision.risk_usd),
        "created_at": now_iso(), "reason": reason, "cycle_id": ctx.cycle_id})
    try:
        if rules.opo_allowed:
            _send(ctx, "opoco", symbol, list_id, ex.place_protected_entry, symbol, decision.qty,
                  decision.limit_price, decision.stop, decision.target, list_id, **plan)
        else:
            _entry_fallback(ctx, trade_id, symbol, decision, list_id, plan)
    except ExchangeError as e:
        update(conn, "trades", trade_id, {"status": "cancelled", "exit_reason": f"erro: {e.code}"})
        raise TradeError("ORDER_FAILED", str(e)) from None
    # dá alguns segundos para o fill (a compra é marketable) e já reconcilia
    for _ in range(5):
        ctx.sleep(2)
        from trader.sync import reconcile_trade
        events = reconcile_trade(ctx, trade(conn, trade_id))
        if trade(conn, trade_id)["status"] != "pending":
            break
    t = trade(conn, trade_id)
    ctx.notify(f"🟢 ENTRADA {symbol} ({setup}) status={t['status']} qty={t['qty'] or plan['qty']} "
               f"limite={plan['limit']} stop={plan['stop']} alvo={plan['target']} risco=${plan['risk_usd']}\n{reason}")
    return {"trade_id": trade_id, "status": t["status"], **plan}


def _entry_fallback(ctx: Ctx, trade_id, symbol, decision, list_id, plan) -> None:
    """Par sem OPO: compra LIMIT IOC e protege em seguida com OCO; OCO falhou 2x = vende a mercado."""
    ex = ctx.ex
    cid = list_id + "-w"
    order = _send(ctx, "buy_ioc", symbol, cid, lambda: ex.client.create_order(
        symbol, "limit", "buy", float(decision.qty), float(decision.limit_price),
        {"timeInForce": "IOC", "clientOrderId": cid}), **plan)
    fills = ex.order_fills(symbol, order["id"])
    if fills["qty"] <= 0:
        update(ctx.conn, "trades", trade_id, {"status": "cancelled", "exit_reason": "ioc_sem_fill"})
        return
    _mark_open(ctx, trade(ctx.conn, trade_id), fills, protect_list_id=None)
    set_protection(ctx, trade(ctx.conn, trade_id), D(plan["stop"]), D(plan["target"]), "fallback")


def _mark_open(ctx: Ctx, t: dict, fills: dict, protect_list_id) -> dict:
    base = t["symbol"].split("/")[0]
    fees = fills["fees"]
    held = fills["qty"] - fees.get(base, D(0))
    cost = fills["quote"] + fees.get("USDT", D(0))
    other = sum((ctx_usd(ctx, a, v) for a, v in fees.items() if a not in (base, "USDT")), D(0))
    entry = fills["quote"] / fills["qty"]
    risk_usd = held * (entry - D(t["initial_stop"])) + held * entry * D(ctx.cfg.risk["fee_pct"]) / 100 * 2
    fields = {"status": "open", "qty": float(held), "entry_price": float(entry), "cost_usd": float(cost),
              "fees_usd": float(other), "opened_at": now_iso(), "risk_usd": float(max(risk_usd, D("0.01"))),
              "usdt_brl": usdt_brl(ctx.ex)}
    if protect_list_id is not None:
        fields["protect_list_id"] = protect_list_id
    update(ctx.conn, "trades", t["id"], fields)
    insert(ctx.conn, "orders", {"ts": now_iso(), "trade_id": t["id"], "symbol": t["symbol"], "side": "buy",
                                "type": "entry", "client_id": t["entry_list_id"] + "-w", "status": "FILLED",
                                "qty": float(fills["qty"]), "avg_price": float(entry),
                                "fee": float(sum(fees.values(), D(0))), "fee_asset": ",".join(fees) or None,
                                "usdt_brl": fields["usdt_brl"]})
    return trade(ctx.conn, t["id"])


def ctx_usd(ctx: Ctx, asset, amount) -> Decimal:
    return usd_value(ctx.ex, asset, amount)


# ---------------------------------------------------------------- proteção e saídas

def _held_qty(ctx: Ctx, t: dict, market: bool = False) -> Decimal:
    rules = ctx.ex.rules(t["symbol"])
    free = ctx.ex.balance().get(rules.base, {"free": D(0)})["free"]
    return rules.floor_qty(min(free, D(t["qty"])) if t["qty"] else free, market=market)


def set_protection(ctx: Ctx, t: dict, stop: Decimal, target: Decimal, tag: str) -> str:
    """Cancela o OCO atual (se houver) e cria outro. Falhou 2x = saída de emergência a mercado."""
    ex, sym = ctx.ex, t["symbol"]
    if t["protect_list_id"]:
        try:
            _send(ctx, "cancel_oco", sym, t["protect_list_id"], ex.cancel_list, sym, t["protect_list_id"])
        except ExchangeError as e:
            if "-2011" not in str(e):
                raise TradeError("CANCEL_FAILED", str(e)) from None
            from trader.sync import reconcile_trade   # lista sumiu: executou? então não recria
            reconcile_trade(ctx, t)
            if trade(ctx.conn, t["id"])["status"] != "open":
                raise TradeError("ALREADY_CLOSED", "a posição já foi encerrada pela exchange") from None
    qty = _held_qty(ctx, t)
    new_id = client_id(t["id"], tag, stop, target, int(ctx.now().timestamp()) // 60)
    for attempt in range(2):
        try:
            _send(ctx, "oco", sym, new_id, ex.place_oco_sell, sym, qty, stop, target, new_id,
                  qty=str(qty), stop=str(stop), target=str(target))
            update(ctx.conn, "trades", t["id"], {"protect_list_id": new_id, "stop_price": float(stop),
                                                 "target_price": float(target), "qty": float(qty)})
            return new_id
        except ExchangeError:
            ctx.sleep(1)
    update(ctx.conn, "trades", t["id"], {"protect_list_id": None})
    emergency_exit(ctx, trade(ctx.conn, t["id"]), "OCO não pôde ser recriado")
    raise TradeError("PROTECTION_FAILED", "OCO falhou 2x; posição vendida a mercado")


def emergency_exit(ctx: Ctx, t: dict, why: str) -> None:
    ctx.notify(f"⚠️ SAÍDA DE EMERGÊNCIA {t['symbol']}: {why}")
    try:
        ctx.ex.cancel_all(t["symbol"])
    except ExchangeError:
        pass
    _sell_market(ctx, t, _held_qty(ctx, t, market=True), "emergency", final=True)


def _sell_market(ctx: Ctx, t: dict, qty: Decimal, reason: str, final: bool) -> dict:
    rules = ctx.ex.rules(t["symbol"])
    price = D(ctx.ex.ticker(t["symbol"])["last"])
    if qty <= 0 or qty * price < rules.min_notional:
        if final:
            _finalize(ctx, trade(ctx.conn, t["id"]), reason + "_poeira", price)
        return {"sold": "0", "note": "abaixo do min notional (poeira)"}
    cid = client_id(t["id"], "sell", reason, qty, int(ctx.now().timestamp()) // 60)
    order = _send(ctx, "market_sell", t["symbol"], cid, ctx.ex.market_sell, t["symbol"], qty, cid, qty=str(qty))
    avg = account_sell(ctx, t, order["id"], reason)
    if final:
        _finalize(ctx, trade(ctx.conn, t["id"]), reason, avg)
    return {"sold": str(qty), "avg_price": float(avg)}


def account_sell(ctx: Ctx, t: dict, order_id: str, kind: str) -> Decimal:
    fills = ctx.ex.order_fills(t["symbol"], order_id)
    if fills["qty"] <= 0:
        return D(0)
    fees = fills["fees"]
    proceeds = fills["quote"] - fees.get("USDT", D(0))
    other = sum((usd_value(ctx.ex, a, v) for a, v in fees.items() if a != "USDT"), D(0))
    t = trade(ctx.conn, t["id"])
    avg = fills["quote"] / fills["qty"]
    update(ctx.conn, "trades", t["id"], {
        "proceeds_usd": float(D(t["proceeds_usd"] or 0) + proceeds),
        "fees_usd": float(D(t["fees_usd"] or 0) + other),
        "qty": float(max(D(t["qty"] or 0) - fills["qty"], D(0)))})
    rate = usdt_brl(ctx.ex)
    insert(ctx.conn, "orders", {"ts": now_iso(), "trade_id": t["id"], "symbol": t["symbol"], "side": "sell",
                                "type": kind, "exchange_id": str(order_id), "status": "FILLED",
                                "qty": float(fills["qty"]), "avg_price": float(avg),
                                "fee": float(sum(fees.values(), D(0))), "fee_asset": ",".join(fees) or None,
                                "usdt_brl": rate})
    return avg


def _finalize(ctx: Ctx, t: dict, reason: str, exit_price) -> None:
    pnl = D(t["proceeds_usd"] or 0) - D(t["cost_usd"] or 0) - D(t["fees_usd"] or 0)
    r_mult = pnl / D(t["risk_usd"]) if t["risk_usd"] else None
    update(ctx.conn, "trades", t["id"], {
        "status": "closed", "closed_at": now_iso(), "exit_price": float(exit_price), "exit_reason": reason,
        "pnl_usd": float(pnl), "r_multiple": float(r_mult) if r_mult is not None else None})
    ctx.notify(f"{'✅' if pnl > 0 else '🔻'} SAÍDA {t['symbol']} ({reason}) PnL ${float(pnl):.2f}"
               + (f" = {float(r_mult):.2f}R" if r_mult is not None else ""))


def move_stop(ctx: Ctx, symbol: str, new_stop, new_target=None) -> dict:
    t = fresh_open_trade(ctx, symbol)
    rules = ctx.ex.rules(symbol)
    last = ctx.ex.ticker(symbol)["last"]
    stop = risk.check_move_stop(rules, t["stop_price"], new_stop, last)
    target = D(t["target_price"])
    if new_target is not None:
        target = risk.check_new_target(rules, new_stop, new_target, last)
    for x in (stop, target):
        if isinstance(x, risk.Rejected):
            audit(ctx.conn, ctx.cycle_id, "move_stop", symbol, "rejected", x.code, {"hint": x.hint})
            raise TradeError(x.code, x.hint)
    audit(ctx.conn, ctx.cycle_id, "move_stop", symbol, "approved",
          detail={"old": t["stop_price"], "new": str(stop), "target": str(target)})
    set_protection(ctx, t, stop, target, "move")
    return {"symbol": symbol, "stop": str(stop), "target": str(target)}


def take_partial(ctx: Ctx, symbol: str, fraction, reason: str) -> dict:
    t = fresh_open_trade(ctx, symbol)
    rules = ctx.ex.rules(symbol)
    last = ctx.ex.ticker(symbol)["last"]
    sell = risk.check_partial(ctx.cfg.risk, rules, D(t["qty"]), fraction, last)
    if isinstance(sell, risk.Rejected):
        audit(ctx.conn, ctx.cycle_id, "take_partial", symbol, "rejected", sell.code, {"hint": sell.hint})
        raise TradeError(sell.code, sell.hint)
    audit(ctx.conn, ctx.cycle_id, "take_partial", symbol, "approved", detail={"sell": str(sell), "reason": reason})
    try:
        _send(ctx, "cancel_oco", symbol, t["protect_list_id"], ctx.ex.cancel_list, symbol, t["protect_list_id"])
    except ExchangeError as e:
        raise TradeError("CANCEL_FAILED", str(e)) from None
    update(ctx.conn, "trades", t["id"], {"protect_list_id": None})
    res = _sell_market(ctx, t, sell, "partial", final=False)
    t = trade(ctx.conn, t["id"])
    set_protection(ctx, t, D(t["stop_price"]), D(t["target_price"]), "partial")
    return {"symbol": symbol, **res, "remaining_qty": trade(ctx.conn, t["id"])["qty"]}


def close_position(ctx: Ctx, symbol: str, reason: str, exit_reason: str = "manual") -> dict:
    t = fresh_open_trade(ctx, symbol)
    audit(ctx.conn, ctx.cycle_id, "close_position", symbol, "approved", detail={"reason": reason})
    if t["protect_list_id"]:
        try:
            _send(ctx, "cancel_oco", symbol, t["protect_list_id"], ctx.ex.cancel_list, symbol, t["protect_list_id"])
        except ExchangeError as e:
            if "-2011" not in str(e):
                raise TradeError("CANCEL_FAILED", str(e)) from None
    update(ctx.conn, "trades", t["id"], {"protect_list_id": None})
    return {"symbol": symbol, **_sell_market(ctx, t, _held_qty(ctx, t, market=True), exit_reason, final=True)}
