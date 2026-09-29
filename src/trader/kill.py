"""Kill switch: pausa, cancela todas as ordens, vende tudo a mercado (menos BNB de taxa), desliga o agendador.
No modo B3 (b3.yaml mode != off): pausa, cancela ordens, zera todo WIN a mercado e desliga as tarefas B3.
No modo B3 (b3.yaml mode != off): pausa, cancela ordens e zera todo WIN a mercado, desliga as tarefas B3.

Manual: `uv run python -m trader.kill --yes`
"""
import subprocess
import sys

from trader.db import set_state, update
from trader.broker.binance_spot import D, ExchangeError, client_id
from trader.trading import Ctx, _finalize, account_sell, active_trades

TASKS = ("let-me-rich-cycle", "let-me-rich-weekly")


def disable_scheduler(tasks=TASKS) -> list[str]:
    out = []
    for task in tasks:
        r = subprocess.run(["schtasks", "/Change", "/TN", task, "/DISABLE"], capture_output=True, text=True)
        out.append(f"agendador {task}: {'desligado' if r.returncode == 0 else 'não encontrado/erro'}")
    return out


def kill(ctx: Ctx, disable_task=disable_scheduler) -> list[str]:
    ex, conn = ctx.ex, ctx.conn
    set_state(conn, "paused", True)                      # primeiro: nenhum ciclo novo opera
    log = ["pausado"]
    symbols = {t["symbol"] for t in active_trades(conn)}
    try:
        symbols |= {o["symbol"] for o in ex.open_orders()}
    except ExchangeError as e:
        log.append(f"não consegui listar ordens abertas: {e}")
    for s in sorted(symbols):
        try:
            ex.cancel_all(s)
            log.append(f"{s}: ordens canceladas")
        except ExchangeError as e:
            log.append(f"{s}: ERRO ao cancelar: {e}")
    trades = {t["symbol"]: t for t in active_trades(conn)}
    for asset, b in ex.balance().items():
        if asset in ("USDT", "BNB"):
            continue
        sym = f"{asset}/USDT"
        try:
            rules = ex.rules(sym)
            qty = rules.floor_qty(b["free"], market=True)
            price = D(ex.ticker(sym)["last"])
            if qty * price < rules.min_notional:
                log.append(f"{sym}: poeira, ignorado")
                continue
            cid = client_id("kill", sym, qty)
            order = ex.market_sell(sym, qty, cid)
            log.append(f"{sym}: vendido {qty}")
            t = trades.pop(sym, None)
            if t and t["status"] == "open":
                avg = account_sell(ctx, t, order["id"], "kill")
                from trader.trading import trade
                _finalize(ctx, trade(conn, t["id"]), "kill", avg)
        except ExchangeError as e:
            log.append(f"{sym}: ERRO ao vender: {e}")
    for t in trades.values():                            # pendentes sem saldo: só cancela o registro
        if t["status"] == "pending":
            update(conn, "trades", t["id"], {"status": "cancelled", "exit_reason": "kill"})
    log += disable_task()
    ctx.notify("🛑 KILL executado:\n" + "\n".join(log))
    return log


def kill_b3(ctx, disable_task=disable_scheduler) -> list[str]:
    """ctx: trading_b3.B3Ctx da variante real."""
    from trader.trading_b3 import flatten_all
    from trader.watchdog import B3_TASKS
    set_state(ctx.conn, "b3_paused", True)
    log = ["B3 pausado"] + flatten_all(ctx, "kill") + disable_task(B3_TASKS)
    ctx.notify("🛑 KILL B3 executado:\n" + "\n".join(log))
    return log


def b3_ctx_or_none(notify):
    """Contexto real do B3 conectado ao MT5, ou None se o modo B3 está desligado."""
    from datetime import date
    from trader.b3.config import load_b3
    from trader.b3.runtime import connect_broker, make_ctx, resolve_contract
    from trader.db import connect
    cfg = load_b3()
    if cfg["mode"] == "off":
        return None
    broker = connect_broker(cfg)
    contract, _, _ = resolve_contract(cfg, broker, date.today())
    return make_ctx(cfg, connect(), broker, contract.symbol, notify=notify)


def main() -> None:
    if "--yes" not in sys.argv:
        sys.exit("uso: python -m trader.kill --yes   (vende TUDO a mercado)")
    from trader.config import load_config, load_secrets
    from trader.db import connect
    from trader.broker.binance_spot import Exchange
    from trader.notify import notify
    secrets = load_secrets()
    say = lambda m: notify(m, secrets)   # noqa: E731
    try:
        b3 = b3_ctx_or_none(say)
        print("\n".join(kill_b3(b3)) if b3 else "B3: mode=off, nada a zerar")
    except Exception as e:  # noqa: BLE001 — o kill do cripto roda mesmo se o MT5 falhar
        print(f"B3: ERRO no kill ({type(e).__name__}: {e}); zere o WIN pelo terminal MT5")
        say(f"❗ KILL B3 falhou: {e}. Zere o WIN pelo terminal MT5.")
    ctx = Ctx(connect(), Exchange(secrets), load_config(), cycle_id="kill", notify=say)
    print("\n".join(kill(ctx)))


if __name__ == "__main__":
    main()
