"""Preflight do modo B3 e montagem do contexto (qual corretora recebe as ordens).

- mode off  -> ABORT
- mode dry  -> ordens no SimBroker (papel) com dados do MT5 real; nada é enviado
- mode live -> ordens no MT5, só se a conta logada é real e bate com account_number
"""
from datetime import date, datetime

from trader import risk_b3 as rk
from trader.b3 import instrument
from trader.broker.base import BrokerError
from trader.broker.sim import SimBroker
from trader.trading_b3 import TZ, B3Ctx, day_state


def connect_broker(cfg):
    from trader.broker.mt5 import MT5Broker
    b = MT5Broker(magic=cfg["magic"], path=cfg["terminal_path"], deviation=cfg["risk"]["slippage_points"])
    b.connect()
    return b


def resolve_contract(cfg, broker, today: date) -> tuple[instrument.Contract, list[str], list[str]]:
    i = cfg["instrument"]
    c = instrument.current_contract(i["root"], today, i["roll_days_before_expiry"])
    spec = broker.symbol_spec(c.symbol)
    problems, warnings = instrument.check_spec(cfg, spec, c)
    if spec.expiration:
        c = instrument.Contract(c.symbol, spec.expiration.date())
    return c, problems, warnings


def expiry_today(cfg, broker, today: date) -> bool:
    """Vencimento do contrato mais próximo (não do que se opera: esse já rolou antes)."""
    front = instrument.upcoming(cfg["instrument"]["root"], today, 1)[0]
    try:
        exp = broker.symbol_spec(front.symbol).expiration
    except BrokerError:
        exp = None
    return instrument.is_expiry_day(cfg["instrument"]["root"], today, exp.date() if exp else None)


def make_ctx(cfg, conn, broker, symbol: str, notify=print, variant: str = "real", now=None) -> B3Ctx:
    """Real em live usa o MT5; todo o resto (dry, sombras) usa papel sobre os dados do MT5."""
    target = broker if (variant == "real" and cfg["mode"] == "live") else SimBroker(broker)
    kw = {"now": now} if now else {}
    return B3Ctx(conn, target, cfg, symbol, variant=variant, cycle_id=f"b3-{variant}", notify=notify, **kw)


def preflight(cfg, conn, broker, now: datetime | None = None) -> dict:
    """ABORT = nada acontece hoje. MANAGE_ONLY = só gerencia/zera, sem entradas novas."""
    now = now or datetime.now(TZ)
    problems, warnings, blocks = [], [], []
    out = {"mode": cfg["mode"], "ts": now.isoformat(timespec="seconds")}
    if cfg["mode"] == "off":
        problems.append("b3.yaml mode=off")
    try:
        if not broker.connected():
            problems.append("terminal MT5 desconectado")
        acc = broker.account()
        out["account"] = {"real": acc.is_real, "number_end": str(acc.number)[-3:], "balance": float(acc.balance)}
        if cfg["mode"] == "live":
            ok, why = rk.send_allowed(cfg, acc)
            if not ok:
                problems.append(why)
            if not acc.trade_allowed:
                problems.append("Algo Trading desligado no terminal ou conta sem permissão para robô")
        c, p, w = resolve_contract(cfg, broker, now.date())
        problems += p
        warnings += w
        out["contract"] = {"symbol": c.symbol, "expiry": c.expiry.isoformat()}
        if cfg["filters"]["block_expiry_day"] and expiry_today(cfg, broker, now.date()):
            blocks.append("dia de vencimento do contrato")
        tk = broker.last_tick(c.symbol)
        lag = abs((now - tk.time).total_seconds())
        out["last_tick"] = {"time": tk.time.isoformat(timespec="seconds"), "bid": float(tk.bid), "ask": float(tk.ask)}
        if lag > 3 * 3600:
            warnings.append(f"último tick há {lag / 3600:.1f}h (fora do pregão, ou fuso do servidor MT5 diferente)")
    except BrokerError as e:
        problems.append(f"MT5: {e}")
    if not problems:
        ctx = make_ctx(cfg, conn, broker, out["contract"]["symbol"], now=lambda: now)
        st = day_state(ctx, {"risk_level": "normal"})
        act = rk.loss_action(cfg, st)
        if act == "total":
            problems.append("perda total máxima atingida: religar só à mão (python -m trader.watchdog --religar --yes)")
        elif act == "day":
            blocks.append("perda diária máxima atingida hoje")
        if st.paused:
            blocks.append("pausado (/resume)")
        if st.consecutive_order_failures >= cfg["risk"]["max_consecutive_order_failures"]:
            blocks.append("circuit breaker de falhas de ordem")
    status = "ABORT" if problems else ("MANAGE_ONLY" if blocks else "OK")
    return {**out, "status": status, "problems": problems, "warnings": warnings, "entries_blocked": blocks}
