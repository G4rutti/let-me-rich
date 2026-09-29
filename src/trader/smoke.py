"""Teste de fumaça do modo B3. Qualquer FALHOU = não liberar live.

`uv run python -m trader.smoke`            MT5 real conectado, SÓ LEITURA (ordens vão para o papel)
`uv run python -m trader.smoke --sim`      sem MT5 (dados sintéticos)
`... --no-llm`                             pula a chamada real da equipe da manhã (analistas simulados)

Banco em memória: nada é gravado em data/trader.db. Rode antes de trocar mode para live e depois de qualquer
atualização do MT5, do Codex ou do Claude Code.
"""
import sys
import traceback
from datetime import date, datetime, timedelta
from decimal import Decimal

from trader import plan as pl
from trader import risk_b3 as rk
from trader import trading_b3 as tb
from trader import watchdog
from trader.b3.config import load_b3
from trader.broker.base import Account, Bar, Position
from trader.broker.sim import Replay, SimBroker
from trader.db import connect, get_state
from trader.executor import VARIANTS, Executor

TZ = tb.TZ


def synthetic(d: date) -> list[Bar]:
    """Ontem em zigue-zague + hoje com range de abertura e rompimento às 09:40 (dados de fumaça, não de mercado)."""
    bars, prev = [], None
    for day_, path in ((d - timedelta(days=1), [129900 + 200 * abs((i % 10) - 5) / 5 for i in range(480)]),
                       (d, [129950 + 150 * abs((i % 10) - 5) / 5 for i in range(30)] + [130050] * 10
                        + [130080, 130120, 130160, 130200] + [130200 + 10 * i for i in range(60)] + [130800] * 400)):
        t = datetime.combine(day_, datetime.min.time(), TZ).replace(hour=9)
        for i, c in enumerate(path):
            c = Decimal(round(c / 5) * 5)
            o = prev if prev is not None else c
            bars.append(Bar(t + timedelta(minutes=i), o, max(o, c) + 10, min(o, c) - 10, c, Decimal(100)))
            prev = c
    return bars


class _Demo(SimBroker):
    """Papel fingindo ser corretora real numa conta demo: exercita as travas de conta sem enviar nada."""
    is_paper = False

    def account(self):
        return Account(1, False, "BRL", Decimal(100), Decimal(100))


class Report:
    def __init__(self):
        self.items = []

    def check(self, name, fn):
        try:
            detail = fn()
            ok = detail is not False
        except Exception as e:  # noqa: BLE001 — smoke reporta, não para
            ok, detail = False, f"{type(e).__name__}: {e}"
            traceback.print_exc()
        self.items.append((name, ok, "" if detail in (True, None) else str(detail)[:300]))
        return ok

    def print(self) -> bool:
        for name, ok, detail in self.items:
            print(f"[{'OK' if ok else 'FALHOU'}] {name}" + (f" — {detail}" if detail else ""))
        bad = [n for n, ok, _ in self.items if not ok]
        print(f"\n{len(self.items) - len(bad)}/{len(self.items)} OK" + (" — NÃO liberar live" if bad else ""))
        return not bad


def run(sim: bool, no_llm: bool) -> bool:
    rep = Report()
    cfg = {k: (dict(v) if hasattr(v, "keys") else v) for k, v in load_b3().items()}
    cfg["mode"] = "dry"
    for k in ("risk", "session", "filters", "executor", "instrument", "reduced_day"):
        cfg[k] = dict(cfg[k])
    cfg["executor"]["sl_confirm_seconds"] = 1
    conn = connect(":memory:")
    now = datetime.now(TZ)
    today = now.date()
    data, symbol = None, None

    # 1. conexão, conta, contrato, especificação, sessão
    if sim:
        rp = Replay(synthetic(today), "WINSIM")
        rp.i = 480
        data, symbol = rp, "WINSIM"
        rep.check("conexão (sim)", lambda: "modo --sim: sem MT5")
    else:
        from trader.b3.runtime import connect_broker, preflight, resolve_contract

        def _conn():
            nonlocal data
            data = connect_broker(load_b3())
            return data.connected() or False
        if rep.check("terminal MT5 conectado", _conn):
            def _acc():
                a = data.account()
                return f"conta ...{str(a.number)[-3:]} real={a.is_real} algo_trading={a.trade_allowed} saldo R${a.balance}"
            rep.check("conta MT5", _acc)

            def _contract():
                nonlocal symbol
                c, problems, warnings = resolve_contract(cfg, data, today)
                symbol = c.symbol
                if problems:
                    return False if not print("problemas:", problems) else False
                return f"{c.symbol} vence {c.expiry} (tick/valor do ponto conferidos) {'; '.join(warnings)}"
            rep.check("contrato vigente e especificação", _contract)
            rep.check("preflight (dry)", lambda: (lambda p: p["status"] != "ABORT" and f"{p['status']} {p['warnings']}")(
                preflight(cfg, conn, data, now)) or False)

            def _clock():
                lag = abs((now - data.last_tick(symbol).time).total_seconds())
                return f"último tick há {lag / 60:.0f} min" if lag < 3 * 3600 or now.weekday() >= 5 or now.hour < 9 \
                    or now.hour >= 18 else False
            rep.check("relógio do servidor MT5 = Brasília", _clock)
    if data is None or symbol is None:
        return rep.print()

    # 2. coletores e equipe da manhã
    def _collectors():
        from trader.collectors import market, news
        m, n = market.collect(), news.collect()
        ok = [k for k, v in m.items() if v != "indisponível"]
        return f"mercados {len(ok)}/{len(m)}, manchetes {len(n['items'])} (falharam: {n['failed_sources']})"
    rep.check("coletores externos", _collectors)

    def _morning():
        from trader import codex, morning
        if no_llm:
            codex_ask = codex.ask
            codex.ask = lambda role, i, d, s: {"macro": {"risk_level": "normal", "events": [], "summary": "sim"},
                                               "context": {"external_bias": "misto", "drivers": [], "summary": ""},
                                               "tech": {"regime": "lateral", "levels": [], "scenarios": []},
                                               "flow": {"aggression": "indisponível", "reading": ""},
                                               "bull": {"bias": "neutral", "arguments": [], "candidate_setups": [],
                                                        "reply": []},
                                               "bear": {"bias": "neutral", "arguments": [], "attacks": []}}[role]
        try:
            d = morning.build_dossier(cfg, conn, data, symbol, now, market={}, news={"note": "", "failed_sources": [],
                                                                                      "items": []})
        finally:
            if no_llm:
                codex.ask = codex_ask
        bad = [k for k, v in d["analysts"].items() if not isinstance(v, dict)]
        return False if bad else f"analistas OK: {', '.join(d['analysts'])}"
    rep.check("equipe da manhã" + (" (simulada)" if no_llm else ""), _morning)

    # 3. plano
    sample = {"date": today.isoformat(), "bias": "long", "risk_level": "normal", "summary": "smoke",
              "setups": [{"id": "s1", "setup": "opening_range_breakout", "direction": "long",
                          "trigger": {"type": "close_above", "timeframe": "5m", "level_ref": "or30_high"},
                          "window": {"from": "09:30", "to": "11:30"}, "stop": {"type": "points", "value": 100},
                          "target": {"type": "r_multiple", "value": 2.0}, "max_entries": 1,
                          "bear_review": {"verdict": "OK", "strength": 2, "points": []}}]}
    rep.check("plano válido aceito", lambda: bool(pl.validate_plan(sample, cfg, today)))

    def _veto():
        try:
            pl.validate_plan({**sample, "setups": [{**sample["setups"][0], "bear_review": {"verdict": "VETO", "strength": 4}}]},
                             cfg, today)
        except pl.PlanError as e:
            return e.code == "BEAR_VETO"
        return False
    rep.check("plano com VETO recusado", _veto)

    # 4. gatilho -> risco -> ordem (papel) -> SL confirmado -> mover stop -> zeragem
    def _cycle():
        ctx = tb.B3Ctx(conn, SimBroker(data), cfg, symbol, variant="smoke", now=lambda: datetime.combine(today, datetime.min.time(), TZ).replace(hour=10),
                       notify=lambda m: None, sleep=lambda s: None)
        tk = data.last_tick(symbol)
        a = rk.check_entry(cfg, rk.DayState(risk_level="normal"), side="long", setup_id="s1", max_entries=1,
                           bid=tk.ask - 5, ask=tk.ask, stop=tk.ask - 100, target=tk.ask + 200, atr5m=100, now=ctx.now())
        if not a.ok:
            return f"risco recusou: {a.code}" and False
        t = tb.enter(ctx, a, setup="smoke", setup_id="s1")
        p = ctx.broker.positions(symbol)[0]
        assert p.sl == a.sl, "SL não confirmado"
        ctx.broker._pos[p.ticket]["p"] = Position(p.ticket, p.symbol, p.side, p.volume, p.price_open - 60, p.sl, p.tp,
                                                    p.magic, p.comment, p.opened_at)
        t = tb.move_stop(ctx, t, float(a.sl) + 50, "smoke")
        log = tb.flatten_all(ctx, "flatten")
        t = tb.trade(conn, t["id"])
        return t["status"] == "closed" and t["exit_reason"] == "flatten" and f"{log[-1]}"
    rep.check("ciclo de ordem em papel (entrada c/ SL, mover stop, zerar)", _cycle)

    def _not_live():
        ctx = tb.B3Ctx(conn, _Demo(data), {**cfg, "mode": "live", "account_number": 999}, symbol, variant="smoke2",
                       notify=lambda m: None, sleep=lambda s: None)
        a = rk.Approved("long", 1, Decimal(1), Decimal(0), Decimal(2), Decimal(100), Decimal(23))
        try:
            tb.enter(ctx, a, setup="smoke", setup_id="s1")
        except tb.TradeError as e:
            return e.code == "NOT_LIVE"
        return False
    rep.check("live bloqueado em conta demo / número errado", _not_live)

    # 5. travas do watchdog
    def _wd(name, prepare):
        def fn():
            v = f"wd_{name}"
            broker = SimBroker(data)
            ctx = tb.B3Ctx(conn, broker, cfg, symbol, variant=v, notify=lambda m: None, sleep=lambda s: None,
                           now=lambda: datetime.combine(today, datetime.min.time(), TZ).replace(hour=10))
            tk = data.last_tick(symbol)
            a = rk.Approved("long", 1, tk.ask, tk.ask - 100, tk.ask + 200, Decimal(100), Decimal(23))
            tb.enter(ctx, a, setup="smoke", setup_id="s1")
            prepare(ctx, broker)
            r = watchdog.run_once(ctx, disable_tasks=lambda names: [])
            return (r["action"] in ("pause", "day", "total") and not broker.positions()
                    and (get_state(conn, f"b3_{v}_paused") or r["action"] == "day") and f"{r['action']}: {r['problems'][:1]}")
        return fn

    def no_sl(ctx, b):
        p = b.positions()[0]
        b._pos[p.ticket]["p"] = Position(p.ticket, p.symbol, p.side, p.volume, p.price_open, None, p.tp, p.magic,
                                          p.comment, p.opened_at)

    def volume(ctx, b):
        p = b.positions()[0]
        b._pos[p.ticket]["p"] = Position(p.ticket, p.symbol, p.side, Decimal(2), p.price_open, p.sl, p.tp, p.magic,
                                          p.comment, p.opened_at)

    def late(ctx, b):
        ctx.now = lambda: datetime.combine(today, datetime.min.time(), TZ).replace(hour=17, minute=45)

    def unknown(ctx, b):
        p = b.positions()[0]
        b.restore(Position(p.ticket + 100, p.symbol, "short", Decimal(1), p.price_open, p.price_open + 100, None, 0,
                           "manual", p.opened_at))

    def offline(ctx, b):
        b.connected = lambda: False

    def daily_loss(ctx, b):
        conn.execute("INSERT INTO b3_trades (variant, mode, day, symbol, setup, setup_id, side, status, contracts, "
                     "signal_price, initial_sl, sl, tp, risk_brl, created_at, closed_at, pnl_brl, r_multiple) VALUES "
                     "(?, 'dry', ?, ?, 'smoke', 's9', 'long', 'closed', 1, 1, 1, 1, 1, 23, ?, ?, -30, -1.3)",
                     (ctx.variant, ctx.today, symbol, datetime.now().astimezone().isoformat(), datetime.now().astimezone().isoformat()))
    for name, prep in (("posição sem SL", no_sl), ("volume > 1", volume), ("fora da janela", late),
                       ("posição desconhecida", unknown), ("terminal desconectado", offline),
                       ("perda diária", daily_loss)):
        rep.check(f"watchdog: {name} -> zera e trava", _wd(name.replace(" ", "_"), prep))

    # 6. executor ponta a ponta sobre replay sintético (gatilho só no fechamento da barra)
    def _executor():
        rp = Replay(synthetic(today), "WINSIM")
        rp.i = 479
        c2 = connect(":memory:")
        pl.save_plan(c2, pl.validate_plan(sample, cfg, today), "plan")
        from trader.b3.runtime import make_ctx
        ctxs = {v: make_ctx(cfg, c2, rp, "WINSIM", notify=lambda m: None, variant=v, now=lambda: rp.now) for v in VARIANTS}
        ex = Executor(ctxs)
        entries = []
        while rp.advance() and rp.now.hour < 12:
            entries += [(rp.now.strftime("%H:%M"), e["variant"]) for e in ex.step(rp.now)["entries"]]
        real = [e for e in entries if e[1] == "real"]
        t = c2.execute("SELECT exit_reason FROM b3_trades WHERE variant='real'").fetchone()
        return bool(real) and real[0][0] == "09:45" and t["exit_reason"] == "target" and f"entradas {entries}"
    rep.check("executor: plano -> gatilho no fechamento -> alvo (replay)", _executor)
    return rep.print()


def main(argv: list[str]) -> int:
    return 0 if run("--sim" in argv, "--no-llm" in argv) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
