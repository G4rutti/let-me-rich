"""Daemon sempre ligado: comandos do Telegram + vigia de fills (sync a cada 60 s, fora do horário do ciclo).

`uv run python -m trader.telegram_daemon`
Só obedece ao TELEGRAM_CHAT_ID configurado; mensagens de qualquer outro chat são ignoradas.
"""
import time
from datetime import datetime, timedelta, timezone

import httpx

from trader.config import load_config, load_secrets
from trader.db import connect, get_state, set_state
from trader.broker.binance_spot import Exchange, ExchangeError
from trader.kill import kill
from trader.lock import exclusive
from trader.notify import notify
from trader.report import compare
from trader.sync import sync
from trader.trading import Ctx, TradeError, portfolio

WATCH_EVERY_S = 60
HELP = ("/status  /posicoes  /pnl  /pause  /resume\n"
        "/b3  /plano  -> modo B3 (WIN)\n"
        "/kill confirmar  -> cancela ordens, vende tudo a mercado, zera o WIN, desliga o agendador")
_b3 = {"ctx": None}


def b3ctx(ctx: Ctx):
    """Conecta ao MT5 só quando algum comando B3 precisa (e reaproveita)."""
    if _b3["ctx"] is None:
        from trader.kill import b3_ctx_or_none
        _b3["ctx"] = b3_ctx_or_none(ctx.notify)
    return _b3["ctx"]


def cmd_b3(ctx: Ctx) -> str:
    from trader.trading_b3 import open_trades, pnl_today
    b = b3ctx(ctx)
    if b is None:
        return "B3: mode=off"
    c = b.conn
    p = pnl_today(b)
    lines = [f"B3 {b.symbol} modo={b.cfg['mode']} ({b.mode}) | pausado={get_state(c, 'b3_paused', False)} | "
             f"trava total={get_state(c, 'b3_halted_total', False)} | trava do dia={get_state(c, 'b3_halted_day') == b.today}",
             f"hoje: realizado R${p['realized_brl']:.2f} aberto R${p['open_brl']:.2f} trades {p['trades_today']}",
             f"resta no dia R${p['daily_loss_left_brl']:.2f} | resta no total R${p['total_loss_left_brl']:.2f}"]
    for t in open_trades(b):
        lines.append(f"posição: {t['side']} {t['contracts']}x @ {t['entry_price']} SL {t['sl']} TP {t['tp']} ({t['setup']})")
    return "\n".join(lines)


def cmd_status(ctx: Ctx) -> str:
    c = ctx.conn
    pf = portfolio(ctx)
    last = c.execute("SELECT * FROM cycles ORDER BY started_at DESC LIMIT 1").fetchone()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    cost = c.execute("SELECT COALESCE(SUM(est_cost_usd),0) s, COUNT(*) n FROM cycles WHERE started_at>=?",
                     (since,)).fetchone()
    lines = [f"modo: {ctx.cfg.risk['mode']} | pausado: {get_state(c, 'paused', False)} | "
             f"falhas seguidas: {get_state(c, 'consecutive_order_failures', 0)}",
             f"banca: ${pf['equity_usd']} (USDT livre ${pf['free_usdt']}) | posições: {len(pf['positions'])}"]
    if last:
        lines.append(f"último ciclo: {last['started_at']} -> {last['status']}")
    lines.append(f"ciclos 24h: {cost['n']} (custo estimado ${cost['s']:.2f}, não é cobrança)")
    return "\n".join(lines)


def cmd_positions(ctx: Ctx) -> str:
    pf = portfolio(ctx)
    if not pf["positions"]:
        return "sem posições"
    return "\n".join(f"{p['symbol']} [{p['status']}] {p['setup']} qty={p['qty']} entrada={p['entry_price']} "
                     f"agora={p['last']} stop={p['stop']} alvo={p['target']} "
                     f"{p.get('unrealized_pct', '')}% R={p.get('r_now', '')}" for p in pf["positions"])


def cmd_pnl(ctx: Ctx) -> str:
    since7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    out = []
    for label, since in (("7 dias", since7), ("total", None)):
        r = compare(ctx.conn, since)
        out.append(f"{label}:\n  agente {r['agente']}\n  sombra {r['sombra']}")
    return "\n".join(out)


def handle(ctx: Ctx, text: str) -> str:
    cmd = text.strip().split()
    if not cmd:
        return HELP
    name = cmd[0].split("@")[0].lower()
    if name == "/status":
        return cmd_status(ctx)
    if name == "/posicoes":
        return cmd_positions(ctx)
    if name == "/pnl":
        return cmd_pnl(ctx)
    if name == "/b3":
        return cmd_b3(ctx)
    if name == "/pause":
        set_state(ctx.conn, "paused", True)
        set_state(ctx.conn, "b3_paused", True)
        return "⏸️ pausado: nenhuma entrada nova (stops e alvos continuam na exchange)"
    if name == "/resume":
        set_state(ctx.conn, "paused", False)
        set_state(ctx.conn, "consecutive_order_failures", 0)
        set_state(ctx.conn, "b3_paused", False)
        set_state(ctx.conn, "b3_consecutive_order_failures", 0)
        extra = (" | B3 com trava de perda total: só `python -m trader.watchdog --religar --yes`"
                 if get_state(ctx.conn, "b3_halted_total", False) else "")
        return "▶️ retomado (contador de falhas zerado)" + extra
    if name == "/kill":
        if len(cmd) < 2 or cmd[1].lower() != "confirmar":
            return "confirme com: /kill confirmar"
        from trader.kill import kill_b3
        try:
            b3 = b3ctx(ctx)
            b3_log = kill_b3(b3) if b3 else ["B3: mode=off"]
        except Exception as e:  # noqa: BLE001 — o kill do cripto roda mesmo se o MT5 falhar
            b3_log = [f"B3: ERRO no kill ({e}); zere o WIN pelo terminal MT5"]
        return "\n".join(b3_log + kill(ctx))
    return HELP


def watch_fills(ctx: Ctx) -> None:
    try:
        with exclusive("cycle"):
            sync(ctx, snapshot=False)   # sync já avisa saídas/erros via notify
    except BlockingIOError:
        pass                            # ciclo do agente rodando: ele mesmo sincroniza


def main() -> None:
    secrets = load_secrets()
    token, chat_id = secrets["TELEGRAM_BOT_TOKEN"], str(secrets["TELEGRAM_CHAT_ID"])
    if not token or not chat_id:
        raise SystemExit("configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID em config/.env")
    ctx = Ctx(connect(), Exchange(secrets), load_config(), cycle_id="daemon", notify=lambda m: notify(m, secrets))
    api = f"https://api.telegram.org/bot{token}"
    offset, last_watch = None, 0.0
    notify("🤖 daemon iniciado\n" + HELP, secrets)
    while True:
        try:
            r = httpx.get(f"{api}/getUpdates", params={"timeout": 20, "offset": offset}, timeout=30).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != chat_id:
                    continue                                   # outro chat: ignora em silêncio
                try:
                    reply = handle(ctx, msg.get("text") or "")
                except (ExchangeError, TradeError) as e:
                    reply = f"erro: {ctx.ex.redact(str(e))}"
                notify(reply, secrets)
        except httpx.HTTPError:
            time.sleep(5)
        if time.time() - last_watch >= WATCH_EVERY_S:
            last_watch = time.time()
            try:
                watch_fills(ctx)
            except (ExchangeError, TradeError) as e:
                notify(f"❗ vigia de fills: {ctx.ex.redact(str(e))}", secrets)


if __name__ == "__main__":
    main()
