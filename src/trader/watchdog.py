"""Watchdog do WIN: 1x/min, processo separado (e também dentro do executor). Fail-closed.

Condições que zeram tudo e pausam: posição sem SL, volume > 1, posição fora da janela, divergência banco x MT5,
terminal desconectado, conta logada errada. Perda diária -> zera e trava o dia. Perda total -> zera, pausa e
desliga as tarefas do agendador (religar só à mão).

`uv run python -m trader.watchdog`                 loop (o agendador roda no pregão; só age em mode live)
`uv run python -m trader.watchdog --religar --yes` limpa a trava de perda total e a pausa (decisão humana)
"""
import sys
import time
from datetime import datetime, timedelta

from trader import risk_b3 as rk
from trader.b3.config import hhmm
from trader.broker.base import BrokerError
from trader.db import get_state
from trader.trading_b3 import B3Ctx, _broker_positions, _key, day_state, halt, reconcile

B3_TASKS = ("let-me-rich-b3-morning", "let-me-rich-b3-plan", "let-me-rich-b3-executor", "let-me-rich-b3-watchdog",
            "let-me-rich-b3-revise", "let-me-rich-b3-close", "let-me-rich-b3-weekly")
GRACE = timedelta(seconds=90)   # o executor zera em flatten_at; o watchdog só age se sobrar posição depois disso


def check(ctx: B3Ctx) -> list[str]:
    """Problemas que exigem zerar e pausar. Não escreve nada."""
    cfg, now = ctx.cfg, ctx.now()
    try:
        if not ctx.broker.connected():
            return ["terminal MT5 desconectado"]
        if not ctx.broker.is_paper:
            ok, why = rk.send_allowed(cfg, ctx.broker.account())
            if not ok:
                return [f"conta: {why}"]
        problems = []
        s = cfg["session"]
        start = datetime.combine(now.date(), hhmm(s["no_entry_before"]), now.tzinfo) - timedelta(minutes=15)
        end = datetime.combine(now.date(), hhmm(s["flatten_at"]), now.tzinfo) + GRACE
        for p in _broker_positions(ctx):
            if p.sl is None:
                problems.append(f"posição {p.ticket} sem SL")
            if p.volume > cfg["risk"]["max_contracts_hard"]:
                problems.append(f"posição {p.ticket} com {p.volume} contratos")
            if not start <= now <= end:
                problems.append(f"posição {p.ticket} fora da janela ({now:%H:%M})")
        return problems + reconcile(ctx)["divergences"]
    except BrokerError as e:
        return [f"MT5: {e}"]


def run_once(ctx: B3Ctx, disable_tasks=None) -> dict:
    problems = check(ctx)
    try:
        act = rk.loss_action(ctx.cfg, day_state(ctx, {"risk_level": "normal"}))
        exposed = bool(_broker_positions(ctx))
    except BrokerError as e:
        act, exposed = None, True
        problems.append(f"MT5: {e}")
    if act == "total" and (exposed or not get_state(ctx.conn, _key(ctx, "halted_total"), False)):
        log = halt(ctx, "total", "perda total máxima atingida")
        if ctx.variant == "real":
            from trader.kill import disable_scheduler
            tasks = (disable_tasks or disable_scheduler)(B3_TASKS)
            ctx.say("\n".join(tasks))
            log += tasks
        return {"action": "total", "problems": problems, "log": log}
    if act == "day" and (exposed or get_state(ctx.conn, _key(ctx, "halted_day")) != ctx.today):
        return {"action": "day", "problems": problems, "log": halt(ctx, "day", "perda diária máxima atingida")}
    if problems:
        return {"action": "pause", "problems": problems, "log": halt(ctx, "pause", "; ".join(problems)[:500])}
    return {"action": None, "problems": [], "log": []}


def main(argv: list[str]) -> int:
    from trader.b3.config import load_b3
    from trader.b3.runtime import connect_broker, make_ctx, resolve_contract
    from trader.config import load_secrets
    from trader.db import connect, set_state
    from trader.notify import notify
    cfg, conn, secrets = load_b3(), connect(), load_secrets()
    if "--religar" in argv:
        if "--yes" not in argv:
            sys.exit("uso: python -m trader.watchdog --religar --yes   (limpa a trava de perda total e a pausa)")
        for k in ("b3_halted_total", "b3_paused", "b3_consecutive_order_failures"):
            set_state(conn, k, False if k != "b3_consecutive_order_failures" else 0)
        print("trava de perda total e pausa limpas. Reative as tarefas do agendador à mão.")
        return 0
    if cfg["mode"] != "live":
        print(f"mode={cfg['mode']}: o watchdog separado só roda em live (em dry o executor tem o seu)")
        return 0
    broker = connect_broker(cfg)
    contract, problems, _ = resolve_contract(cfg, broker, datetime.now().date())
    ctx = make_ctx(cfg, conn, broker, contract.symbol, notify=lambda m: notify(m, secrets))
    if problems:
        ctx.say("❗ B3 watchdog: " + "; ".join(problems))
    end = datetime.combine(ctx.now().date(), hhmm(cfg["session"]["flatten_at"]), ctx.now().tzinfo) + timedelta(minutes=10)
    while ctx.now() < end:
        r = run_once(ctx)
        if r["action"]:
            print(r)
        time.sleep(cfg["executor"]["watchdog_every_s"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
