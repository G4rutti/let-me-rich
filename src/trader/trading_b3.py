"""Operações do WIN via Broker. Toda escrita na corretora passa por aqui, SEMPRE depois do risk_b3.

Padrão de cada ordem: audit 'intent' (fsync) -> corretora -> audit 'result' | 'error'.
A corretora é a fonte da verdade; b3_trades é espelho + histórico. `variant` separa o real das sombras.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from trader import risk_b3 as rk
from trader.broker.base import BrokerError
from trader.db import get_state, insert, now_iso, set_state, update
from trader.journal import audit

TZ = ZoneInfo("America/Sao_Paulo")
D = rk.D


class TradeError(Exception):
    def __init__(self, code: str, hint: str):
        super().__init__(f"{code}: {hint}")
        self.code, self.hint = code, hint


@dataclass
class B3Ctx:
    conn: object
    broker: object
    cfg: object
    symbol: str                                   # contrato vigente (ex.: WINV26)
    variant: str = "real"
    cycle_id: str = "b3"
    notify: Callable[[str], object] = print
    now: Callable[[], datetime] = field(default=lambda: datetime.now(TZ))
    sleep: Callable[[float], None] = time.sleep

    @property
    def mode(self) -> str:
        """Modo gravado no trade: live só se as ordens vão de verdade para a corretora."""
        return "dry" if self.broker.is_paper else "live"

    @property
    def today(self) -> str:
        return self.now().astimezone(TZ).date().isoformat()

    @property
    def root(self) -> str:
        return self.cfg["instrument"]["root"]

    def say(self, text: str) -> None:
        if self.variant == "real":            # sombras não falam no Telegram
            self.notify(text)


def trade(conn, trade_id: int) -> dict:
    row = conn.execute("SELECT * FROM b3_trades WHERE id=?", (trade_id,)).fetchone()
    if not row:
        raise TradeError("NO_TRADE", f"trade {trade_id} não existe")
    return dict(row)


def open_trades(ctx: B3Ctx) -> list[dict]:
    return [dict(r) for r in ctx.conn.execute(
        "SELECT * FROM b3_trades WHERE variant=? AND mode=? AND status IN ('pending','open') ORDER BY id",
        (ctx.variant, ctx.mode))]


# ---------------------------------------------------------------- estado de risco

def _key(ctx: B3Ctx, name: str) -> str:
    return f"b3_{name}" if ctx.variant == "real" else f"b3_{ctx.variant}_{name}"


def failures(ctx: B3Ctx) -> int:
    return get_state(ctx.conn, _key(ctx, "consecutive_order_failures"), 0)


def _order_ok(ctx: B3Ctx) -> None:
    set_state(ctx.conn, _key(ctx, "consecutive_order_failures"), 0)


def _order_failed(ctx: B3Ctx, what: str, err: Exception) -> None:
    n = failures(ctx) + 1
    set_state(ctx.conn, _key(ctx, "consecutive_order_failures"), n)
    if n >= ctx.cfg["risk"]["max_consecutive_order_failures"]:
        set_state(ctx.conn, _key(ctx, "paused"), True)
        ctx.say(f"🛑 B3 CIRCUIT BREAKER: {n} falhas de ordem seguidas ({what}: {err}). Pausado; /resume após revisar.")


def _send(ctx: B3Ctx, action: str, cid: str, fn, /, *args, **detail):
    audit(ctx.conn, ctx.cycle_id, f"b3_{action}", ctx.symbol, "intent",
          detail={"client_id": cid, "variant": ctx.variant, "mode": ctx.mode, **detail})
    try:
        res = fn(*args)
    except BrokerError as e:
        audit(ctx.conn, ctx.cycle_id, f"b3_{action}", ctx.symbol, "error", e.code, {"client_id": cid, "error": str(e)})
        _order_failed(ctx, action, e)
        raise
    audit(ctx.conn, ctx.cycle_id, f"b3_{action}", ctx.symbol, "result", detail={"client_id": cid})
    _order_ok(ctx)
    return res


def open_pnl(ctx: B3Ctx) -> Decimal:
    """Resultado aberto das posições do bot, a preço de saída (bid na compra, ask na venda), custos incluídos."""
    total = D(0)
    trades = [t for t in open_trades(ctx) if t["status"] == "open"]
    if not trades:
        return total
    tk = ctx.broker.last_tick(ctx.symbol)
    for t in trades:
        px = tk.bid if t["side"] == "long" else tk.ask
        total += rk.pnl_brl(ctx.cfg, t["side"], t["entry_price"], px, t["contracts"])
    return total


def capital_start(ctx: B3Ctx) -> dict:
    """Marco zero da perda total, gravado no primeiro uso de cada modo."""
    key = _key(ctx, f"capital_start_{ctx.mode}")
    cs = get_state(ctx.conn, key)
    if cs is None:
        cs = {"ts": now_iso(), "brl": ctx.cfg["capital_start_brl"]}
        set_state(ctx.conn, key, cs)
    return cs


def day_state(ctx: B3Ctx, plan: dict | None = None, setup_status: str = "NEUTRO") -> rk.DayState:
    conn, today = ctx.conn, ctx.today
    base = "FROM b3_trades WHERE variant=? AND mode=?"
    args = (ctx.variant, ctx.mode)
    realized = conn.execute(f"SELECT COALESCE(SUM(pnl_brl),0) s {base} AND status='closed' AND day=?",
                            (*args, today)).fetchone()["s"]
    cs = capital_start(ctx)
    total = conn.execute(f"SELECT COALESCE(SUM(pnl_brl),0) s {base} AND status='closed' AND created_at>=?",
                         (*args, cs["ts"])).fetchone()["s"]
    rows = conn.execute(f"SELECT setup_id, COUNT(*) n {base} AND day=? AND status!='cancelled' GROUP BY setup_id",
                        (*args, today)).fetchall()
    last_stop = conn.execute(f"SELECT MAX(closed_at) t {base} AND day=? AND exit_reason='stop'",
                             (*args, today)).fetchone()["t"]
    op = open_pnl(ctx)
    return rk.DayState(
        realized_today_brl=D(realized), open_pnl_brl=op, total_pnl_brl=D(total) + op,
        trades_today=sum(r["n"] for r in rows), entries_by_setup={r["setup_id"]: r["n"] for r in rows},
        open_position=bool(open_trades(ctx)) or bool(_broker_positions(ctx)),
        last_stop_at=datetime.fromisoformat(last_stop).astimezone(TZ) if last_stop else None,
        consecutive_order_failures=failures(ctx), paused=bool(get_state(conn, _key(ctx, "paused"), False)),
        halted_today=get_state(conn, _key(ctx, "halted_day")) == today,
        halted_total=bool(get_state(conn, _key(ctx, "halted_total"), False)),
        risk_level=(plan or {}).get("risk_level", "fora"), bias=(plan or {}).get("bias", "neutral"),
        setup_status=setup_status)


def _broker_positions(ctx: B3Ctx) -> list:
    return [p for p in ctx.broker.positions() if p.symbol.startswith(ctx.root)]


# ---------------------------------------------------------------- entrada

def enter(ctx: B3Ctx, a: rk.Approved, *, setup: str, setup_id: str, plan: dict | None = None,
          context: dict | None = None) -> dict:
    """Envia a entrada aprovada com SL+TP no mesmo envio e confirma o SL na corretora."""
    if not ctx.broker.is_paper:
        ok, why = rk.send_allowed(ctx.cfg, ctx.broker.account())
        if not ok:
            raise TradeError("NOT_LIVE", why)
    plan = plan or {}
    tid = insert(ctx.conn, "b3_trades", {
        "variant": ctx.variant, "mode": ctx.mode, "day": ctx.today, "symbol": ctx.symbol, "setup": setup,
        "setup_id": setup_id, "side": a.side, "status": "pending", "contracts": a.contracts,
        "signal_price": float(a.entry), "initial_sl": float(a.sl), "sl": float(a.sl), "tp": float(a.tp),
        "risk_brl": float(a.risk_brl), "created_at": now_iso(), "plan_version": plan.get("version"),
        "bias": plan.get("bias"), "risk_level": plan.get("risk_level"), "regime": (context or {}).get("regime"),
        "context_json": json.dumps(context or {}, default=str)[:4000]})
    comment = f"lmr{tid}"
    update(ctx.conn, "b3_trades", tid, {"comment": comment})
    try:
        fill = _send(ctx, "entry", comment, ctx.broker.place_entry, ctx.symbol, a.side, D(a.contracts), a.sl, a.tp,
                     ctx.cfg["magic"], comment, side=a.side, sl=str(a.sl), tp=str(a.tp), risk_brl=str(a.risk_brl))
    except BrokerError as e:
        update(ctx.conn, "b3_trades", tid, {"status": "cancelled", "exit_reason": f"erro: {e.code}"})
        ctx.say(f"❗ B3 entrada {a.side} {ctx.symbol} falhou: {e}")
        raise TradeError("ORDER_FAILED", str(e)) from None
    slip = (fill.price - a.entry) * (1 if a.side == "long" else -1)
    update(ctx.conn, "b3_trades", tid, {"status": "open", "position_ticket": fill.position_ticket,
                                        "entry_price": float(fill.price), "slippage_points": float(slip),
                                        "opened_at": now_iso()})
    ctx.say(f"🟢 B3 ENTRADA {ctx.symbol} {a.side.upper()} ({setup}) {a.contracts}x @ {fill.price} "
            f"(sinal {a.entry}, slip {slip}) SL {a.sl} TP {a.tp} risco R${a.risk_brl:.2f} [{ctx.mode}]")
    verify_sl(ctx, trade(ctx.conn, tid))
    return trade(ctx.conn, tid)


def verify_sl(ctx: B3Ctx, t: dict) -> bool:
    """Posição sem o SL esperado na corretora: tenta pôr uma vez; não confirmou até o prazo = zera a mercado."""
    tick = D(ctx.cfg["instrument"]["tick_points"])
    want = D(t["sl"])
    deadline = time.monotonic() + ctx.cfg["executor"]["sl_confirm_seconds"]
    fixed = False
    while True:
        p = next((p for p in ctx.broker.positions(ctx.symbol) if p.ticket == t["position_ticket"]), None)
        if p is None:
            return True                           # já saiu (stop/alvo executou): o sync contabiliza
        if p.sl is not None and abs(p.sl - want) <= tick:
            return True
        if not fixed:
            fixed = True
            try:
                _send(ctx, "set_sl", t["comment"], ctx.broker.modify_sl, p.ticket, want, sl=str(want))
            except BrokerError:
                pass
        elif time.monotonic() > deadline:
            ctx.say(f"⚠️ B3 {ctx.symbol}: posição sem SL confirmado ({p.sl} != {want}); zerando a mercado")
            close_trade(ctx, t, "sem_sl")
            return False
        ctx.sleep(0.5)


# ---------------------------------------------------------------- saídas

def finalize(ctx: B3Ctx, t: dict, exit_price, reason: str) -> dict:
    pnl = rk.pnl_brl(ctx.cfg, t["side"], t["entry_price"], exit_price, t["contracts"])
    r_mult = pnl / D(t["risk_brl"]) if t["risk_brl"] else None
    update(ctx.conn, "b3_trades", t["id"], {
        "status": "closed", "closed_at": now_iso(), "exit_price": float(exit_price), "exit_reason": reason,
        "pnl_brl": float(pnl), "r_multiple": float(r_mult) if r_mult is not None else None})
    ctx.say(f"{'✅' if pnl > 0 else '🔻'} B3 SAÍDA {t['symbol']} {t['side']} ({reason}) @ {exit_price} "
            f"R${float(pnl):.2f}" + (f" = {float(r_mult):.2f}R" if r_mult is not None else ""))
    return trade(ctx.conn, t["id"])


def close_trade(ctx: B3Ctx, t: dict, reason: str) -> dict:
    try:
        fill = _send(ctx, "close", t["comment"], ctx.broker.close_position, t["position_ticket"], f"{t['comment']}x",
                     reason=reason)
    except BrokerError as e:
        if e.code == "NO_POSITION":           # saiu por stop/alvo enquanto isso
            reconcile(ctx)
            return trade(ctx.conn, t["id"])
        raise TradeError("CLOSE_FAILED", str(e)) from None
    return finalize(ctx, trade(ctx.conn, t["id"]), fill.price, reason)


def move_stop(ctx: B3Ctx, t: dict, new_sl, why: str) -> dict:
    tk = ctx.broker.last_tick(ctx.symbol)
    new = rk.check_move_stop(ctx.cfg, t["side"], t["sl"], new_sl, tk.bid, tk.ask)
    if isinstance(new, rk.Rejected):
        audit(ctx.conn, ctx.cycle_id, "b3_move_stop", ctx.symbol, "rejected", new.code, {"hint": new.hint})
        raise TradeError(new.code, new.hint)
    try:
        _send(ctx, "move_stop", t["comment"], ctx.broker.modify_sl, t["position_ticket"], new, old=t["sl"], new=str(new))
    except BrokerError as e:
        raise TradeError("MOVE_FAILED", str(e)) from None
    update(ctx.conn, "b3_trades", t["id"], {"sl": float(new)})
    ctx.say(f"🛡️ B3 {ctx.symbol}: stop {t['sl']} -> {new} ({why})")
    return trade(ctx.conn, t["id"])


def _exit_reason(ctx: B3Ctx, t: dict, price: Decimal) -> str:
    tick = D(ctx.cfg["instrument"]["tick_points"])
    if abs(price - D(t["tp"])) <= 2 * tick or ((price >= D(t["tp"])) if t["side"] == "long" else (price <= D(t["tp"]))):
        return "target"
    if D(t["sl"]) == D(t["entry_price"]):
        return "breakeven"
    return "stop"


def reconcile(ctx: B3Ctx) -> dict:
    """Espelha a corretora no banco. Divergência = posição/ordem que um lado conhece e o outro não."""
    events, divergences = [], []
    positions = {p.ticket: p for p in _broker_positions(ctx)}
    known = set()
    for t in open_trades(ctx):
        if t["status"] == "pending":
            if (ctx.now() - datetime.fromisoformat(t["created_at"])).total_seconds() > 120:
                update(ctx.conn, "b3_trades", t["id"], {"status": "cancelled", "exit_reason": "sem_fill"})
                divergences.append(f"trade {t['id']} ficou pendente sem posição")
            continue
        known.add(t["position_ticket"])
        if t["position_ticket"] in positions:
            p = positions[t["position_ticket"]]
            if p.volume > t["contracts"]:
                divergences.append(f"posição {p.ticket} com {p.volume} contratos (esperado {t['contracts']})")
            continue
        fills = ctx.broker.exit_fills(t["position_ticket"])
        if fills:
            px = sum((f.price * f.volume for f in fills), D(0)) / sum((f.volume for f in fills), D(0))
            finalize(ctx, t, px, _exit_reason(ctx, t, px))
            events.append(f"trade {t['id']} saiu na corretora @ {px}")
        else:
            tk = ctx.broker.last_tick(ctx.symbol)
            finalize(ctx, t, tk.bid if t["side"] == "long" else tk.ask, "desconhecido")
            divergences.append(f"trade {t['id']} sumiu da corretora sem execução registrada")
    for ticket, p in positions.items():
        if ticket not in known:
            divergences.append(f"posição {ticket} {p.symbol} {p.side} {p.volume} que o banco não conhece")
    for o in ctx.broker.orders():
        if o.symbol.startswith(ctx.root):
            divergences.append(f"ordem pendente {o.ticket} {o.symbol} que o bot não usa")
    return {"events": events, "divergences": divergences}


def flatten_all(ctx: B3Ctx, reason: str) -> list[str]:
    """Cancela ordens e zera TODA posição do WIN nesta conta (inclusive desconhecida)."""
    log = []
    try:
        _send(ctx, "cancel_all", f"flatten-{reason}", ctx.broker.cancel_all, None)
        log.append("ordens canceladas")
    except BrokerError as e:
        log.append(f"ERRO ao cancelar ordens: {e}")
    by_ticket = {t["position_ticket"]: t for t in open_trades(ctx) if t["status"] == "open"}
    try:
        positions = _broker_positions(ctx)
    except BrokerError as e:
        return log + [f"ERRO ao listar posições: {e}"]
    for p in positions:
        try:
            fill = _send(ctx, "flatten", f"flatten-{p.ticket}", ctx.broker.close_position, p.ticket, "lmr-flat",
                         reason=reason)
            log.append(f"{p.symbol} {p.side} {p.volume} zerado @ {fill.price}")
            if p.ticket in by_ticket:
                finalize(ctx, trade(ctx.conn, by_ticket.pop(p.ticket)["id"]), fill.price, reason)
        except BrokerError as e:
            log.append(f"ERRO ao zerar {p.ticket}: {e}")
    try:
        log += reconcile(ctx)["events"]       # trades do banco que já tinham saído
    except BrokerError as e:
        log.append(f"ERRO no reconcile: {e}")
    return log


def halt(ctx: B3Ctx, level: str, why: str) -> list[str]:
    """level: pause | day | total. Zera tudo e trava."""
    log = flatten_all(ctx, {"pause": "watchdog", "day": "daily_loss", "total": "total_loss"}[level])
    if level == "day":
        set_state(ctx.conn, _key(ctx, "halted_day"), ctx.today)
    else:
        set_state(ctx.conn, _key(ctx, "paused"), True)
    if level == "total":
        set_state(ctx.conn, _key(ctx, "halted_total"), True)
    ctx.say(f"🛑 B3 TRAVA ({level}): {why}\n" + "\n".join(log))
    return log


def pnl_today(ctx: B3Ctx) -> dict:
    st = day_state(ctx)
    return {"realized_brl": float(st.realized_today_brl), "open_brl": float(st.open_pnl_brl),
            "total_since_start_brl": float(st.total_pnl_brl), "trades_today": st.trades_today,
            "daily_loss_left_brl": float(D(ctx.cfg["risk"]["daily_loss_max_brl"]) + st.realized_today_brl + st.open_pnl_brl),
            "total_loss_left_brl": float(D(ctx.cfg["risk"]["total_loss_max_brl"]) + st.total_pnl_brl)}


def restore_paper(ctx: B3Ctx) -> None:
    """Executor reiniciado em papel: devolve ao SimBroker as posições abertas do banco."""
    from trader.broker.base import Position
    for t in open_trades(ctx):
        if t["status"] == "open" and t["position_ticket"]:
            ctx.broker.restore(Position(t["position_ticket"], t["symbol"], t["side"], D(t["contracts"]),
                                        D(t["entry_price"]), D(t["sl"]), D(t["tp"]), ctx.cfg["magic"],
                                        t["comment"], datetime.fromisoformat(t["opened_at"])))


def day_of(dt: datetime) -> date:
    return dt.astimezone(TZ).date()
