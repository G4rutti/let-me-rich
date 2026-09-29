"""Reconciliação com a exchange (fonte da verdade) e preflight.

- entrada OPOCO preenchida -> posição aberta (o OCO já está ativo na exchange)
- entrada parcial/parada após timeout -> cancela o resto e protege o que foi comprado
- OCO executado entre ciclos -> registra a saída
- posição sem OCO ativo -> recria o stop na hora (ou vende se o preço já passou do stop)
- saldo sem trade conhecido (órfão) -> protege com stop por ATR
"""
from datetime import datetime, timezone

from trader import risk
from trader.db import get_state, insert, now_iso, update
from trader.broker.binance_spot import D, ExchangeError
from trader.indicators import atr
from trader.journal import audit, orphan_intents
from trader.trading import (ACTIVE, Ctx, TradeError, _finalize, _held_qty, _mark_open, _sell_market, _send,
                            account_sell, active_trades, emergency_exit, portfolio, set_protection, status_of,
                            trade, usdt_brl)


def _fetch(ctx: Ctx, symbol: str, cid: str) -> dict | None:
    try:
        return ctx.ex.fetch_order_by_client_id(symbol, cid)
    except ExchangeError as e:
        if e.code in ("ORDERNOTFOUND",) or "-2013" in str(e):
            return None
        raise


def reconcile_trade(ctx: Ctx, t: dict) -> list[str]:
    if t["status"] == "pending":
        return _reconcile_pending(ctx, t)
    if t["status"] == "open":
        return _reconcile_open(ctx, t)
    return []


def _reconcile_pending(ctx: Ctx, t: dict) -> list[str]:
    ex, sym, lid = ctx.ex, t["symbol"], t["entry_list_id"]
    w = _fetch(ctx, sym, lid + "-w")
    age_min = (ctx.now() - datetime.fromisoformat(t["created_at"])).total_seconds() / 60
    timeout = age_min > ctx.cfg.risk["partial_fill_timeout_min"]
    if w is None:
        if timeout:
            update(ctx.conn, "trades", t["id"], {"status": "cancelled", "exit_reason": "ordem_nao_encontrada"})
            return [f"{sym}: entrada não encontrada na exchange; cancelada"]
        return []
    ws = status_of(w)
    if ws == "FILLED":
        _mark_open(ctx, t, ex.order_fills(sym, w["id"]), protect_list_id=lid)
        return [f"{sym}: entrada executada, OCO ativo"]
    if ws in ACTIVE and not timeout:
        return []
    if ws in ACTIVE:
        _send(ctx, "cancel_entry", sym, lid, ex.cancel_list, sym, lid)
    if D(w.get("filled") or 0) <= 0:
        update(ctx.conn, "trades", t["id"], {"status": "cancelled", "exit_reason": f"entrada_{ws.lower()}"})
        return [f"{sym}: entrada não executada ({ws}); cancelada"]
    t = _mark_open(ctx, t, ex.order_fills(sym, w["id"]), protect_list_id=None)
    update(ctx.conn, "trades", t["id"], {"protect_list_id": None})
    return [f"{sym}: entrada parcial"] + _reprotect(ctx, trade(ctx.conn, t["id"]), "entrada parcial")


def _reconcile_open(ctx: Ctx, t: dict) -> list[str]:
    ex, sym, pid = ctx.ex, t["symbol"], t["protect_list_id"]
    if not pid:
        return _reprotect(ctx, t, "sem OCO registrado")
    s, tp = _fetch(ctx, sym, pid + "-s"), _fetch(ctx, sym, pid + "-t")
    ss, ts = (status_of(s) if s else "MISSING"), (status_of(tp) if tp else "MISSING")
    if ts == "FILLED":
        avg = account_sell(ctx, t, tp["id"], "target")
        _finalize(ctx, trade(ctx.conn, t["id"]), "target", avg)
        return [f"{sym}: alvo executado"]
    if ss == "FILLED":
        avg = account_sell(ctx, t, s["id"], "stop")
        _finalize(ctx, trade(ctx.conn, t["id"]), "stop", avg)
        return [f"{sym}: stop executado"]
    if ss in ACTIVE and ts in ACTIVE and ts != "PARTIALLY_FILLED":
        return []
    # OCO quebrado (cancelado por fora, expirado, parcial no alvo): contabiliza o que executou e protege o resto
    for leg in (s, tp):
        if leg and D(leg.get("filled") or 0) > 0:
            account_sell(ctx, t, leg["id"], "partial_leg")
    try:
        ex.cancel_all(sym)
    except ExchangeError:
        pass
    update(ctx.conn, "trades", t["id"], {"protect_list_id": None})
    return _reprotect(ctx, trade(ctx.conn, t["id"]), f"OCO inativo (stop={ss}, alvo={ts})")


def _reprotect(ctx: Ctx, t: dict, why: str) -> list[str]:
    """Posição sem proteção. protect_list_id já é None aqui (evita recursão com set_protection)."""
    sym = t["symbol"]
    rules = ctx.ex.rules(sym)
    price = D(ctx.ex.ticker(sym)["last"])
    held = _held_qty(ctx, t)
    if held * price < rules.min_notional:
        _finalize(ctx, t, "poeira", price)
        return [f"{sym}: restante abaixo do mínimo; encerrado como poeira"]
    if price <= D(t["stop_price"]):
        emergency_exit(ctx, t, f"{why}; preço {price} já abaixo do stop {t['stop_price']}")
        return [f"{sym}: vendido a mercado (preço abaixo do stop)"]
    target = D(t["target_price"])
    if target <= price:   # alvo já ultrapassado: fecha com lucro em vez de OCO inválido
        _sell_market(ctx, t, _held_qty(ctx, t, market=True), "target", final=True)
        return [f"{sym}: alvo já ultrapassado; vendido a mercado"]
    try:
        set_protection(ctx, t, D(t["stop_price"]), target, "reprotect")
    except TradeError as e:
        return [f"{sym}: {e}"]
    ctx.notify(f"🛡️ {sym}: stop recriado ({why})")
    return [f"{sym}: stop recriado ({why})"]


def _orphans(ctx: Ctx, bal: dict) -> list[str]:
    """Saldo que não pertence a nenhum trade (ex.: compra manual). Protege só a parte livre."""
    events = []
    tracked = {}
    for t in active_trades(ctx.conn):
        base = t["symbol"].split("/")[0]
        tracked[base] = tracked.get(base, D(0)) + D(t["qty"] if t["qty"] is not None else t["planned_qty"])
    for asset, b in bal.items():
        if asset in ("USDT", "BNB") or asset in ctx.cfg.universe["blacklist"]:
            continue
        sym = f"{asset}/USDT"
        try:
            rules = ctx.ex.rules(sym)
        except ExchangeError:
            continue
        extra = rules.floor_qty(b["free"] - tracked.get(asset, D(0)))
        if extra <= 0:
            continue
        price = D(ctx.ex.ticker(sym)["last"])
        if extra * price < rules.min_notional * D(ctx.cfg.risk["partial_min_notional_buffer"]):
            continue
        if not ctx.cfg.risk.get("protect_orphans", True):
            events.append(f"{sym}: saldo órfão de ${float(extra * price):.2f} sem stop (protect_orphans=false)")
            continue
        cat = ctx.cfg.category(sym)
        a = D(atr(ctx.ex.ohlcv(sym, "1h", 60)) or 0)
        stop_pct = D(ctx.cfg.risk["stop_max_pct"][cat]) / 100
        stop = rules.floor_price(max(price - 2 * a, price * (1 - stop_pct)))
        target = rules.floor_price(price + 3 * (price - stop))
        tid = insert(ctx.conn, "trades", {
            "mode": "live", "symbol": sym, "category": cat, "setup": "orphan", "horizon": "swing", "status": "open",
            "entry_list_id": f"orphan-{sym}-{now_iso()}", "entry_limit": float(price), "planned_qty": float(extra),
            "qty": float(extra), "entry_price": float(price), "initial_stop": float(stop), "stop_price": float(stop),
            "target_price": float(target), "risk_usd": float(extra * (price - stop)), "cost_usd": float(extra * price),
            "created_at": now_iso(), "opened_at": now_iso(), "reason": "saldo órfão encontrado no sync",
            "cycle_id": ctx.cycle_id, "usdt_brl": usdt_brl(ctx.ex)})
        events += _reprotect(ctx, trade(ctx.conn, tid), "saldo órfão")
    return events


def sync(ctx: Ctx, snapshot: bool = True) -> dict:
    events = []
    for t in active_trades(ctx.conn):
        try:
            events += reconcile_trade(ctx, t)
        except (ExchangeError, TradeError) as e:
            events.append(f"{t['symbol']}: ERRO no reconcile: {e}")
            audit(ctx.conn, ctx.cycle_id, "sync", t["symbol"], "error", getattr(e, "code", None), {"error": str(e)})
    bal = ctx.ex.balance()
    try:
        events += _orphans(ctx, bal)
    except (ExchangeError, TradeError) as e:
        events.append(f"ERRO ao tratar órfãos: {e}")
    pf = portfolio(ctx)
    ts = now_iso()
    if not snapshot:
        for e in events:
            if "ERRO" in e:
                ctx.notify("❗ " + e)
        return {"events": events, "portfolio": pf}
    insert(ctx.conn, "equity_history", {"ts": ts, "equity_usd": pf["equity_usd"], "usdt_brl": usdt_brl(ctx.ex)})
    for asset, b in bal.items():
        insert(ctx.conn, "positions_snapshot", {"ts": ts, "cycle_id": ctx.cycle_id, "asset": asset,
                                                "free": float(b["free"]), "locked": float(b["locked"]),
                                                "usd_value": None})
    for e in events:
        if "ERRO" in e:
            ctx.notify("❗ " + e)
    return {"events": events, "portfolio": pf}


def preflight(ctx: Ctx) -> dict:
    """ABORT = o Claude não faz nada. MANAGE_ONLY = sem entradas novas, mas pode gerenciar posições."""
    cfg, conn = ctx.cfg.risk, ctx.conn
    problems, warnings = [], []
    if cfg["mode"] == "off":
        problems.append("mode=off em risk.yaml")
    if get_state(conn, "paused", False):
        problems.append("bot pausado (/resume)")
    try:
        offset = ctx.ex.server_time_offset_ms()
        if abs(offset) > 1000:
            warnings.append(f"relógio {offset} ms fora (ccxt compensa; sincronize o Windows)")
        if cfg["mode"] == "live":
            rs = ctx.ex.api_restrictions()
            if rs.get("enableWithdrawals"):
                problems.append("chave com SAQUE habilitado: desabilite na Binance")
            if not rs.get("ipRestrict"):
                problems.append("chave sem whitelist de IP")
            if not rs.get("enableSpotAndMarginTrading"):
                problems.append("chave sem permissão de Spot Trading")
            for k in ("enableFutures", "enableMargin", "permitsUniversalTransfer", "enableInternalTransfer"):
                if rs.get(k):
                    warnings.append(f"chave com {k}=true (desnecessário)")
    except ExchangeError as e:
        problems.append(f"API indisponível: {e}")
    if orphan := orphan_intents(conn):
        warnings.append(f"{len(orphan)} ordem(ns) com intent sem resultado: {orphan[:3]}")
    status = "ABORT" if problems else "OK"
    entry_block = None
    if status == "OK":
        try:
            pf = portfolio(ctx)
            from trader.trading import risk_state
            st = risk_state(ctx, pf, "NEUTRO", None)
            g = risk.gate(cfg, st, ctx.now())
            if g is not None:
                status, entry_block = "MANAGE_ONLY", f"{g.code}: {g.hint}"
        except ExchangeError as e:
            status, problems = "ABORT", [f"API indisponível: {e}"]
    return {"status": status, "mode": cfg["mode"], "problems": problems, "warnings": warnings,
            "entries_blocked": entry_block, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
