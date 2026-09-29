"""Executor do plano do dia (loop curto, só no pregão). O LLM nunca está aqui: gatilhos são determinísticos.

Cada passo: dados -> reconcile -> gerencia posição (+1R = stop na entrada, invalidação, zeragem por horário)
-> gatilhos em fechamento de barra -> risk_b3.check_entry -> trading_b3.enter.
Roda a variante real e, com os mesmos dados, as sombras em papel (sombra_regra, sombra_sem_macro).
Watchdog embutido a cada `watchdog_every_s`.

`uv run python -m trader.executor`
"""
import json
import sys
import time
from datetime import date, datetime, timedelta

from trader import plan as pl
from trader import risk_b3 as rk
from trader import trading_b3 as tb
from trader import watchdog
from trader.b3 import features as ft
from trader.b3.config import hhmm
from trader.b3.regime import regime as b3_regime
from trader.broker.base import BrokerError
from trader.broker.sim import TF_MIN, resample
from trader.db import get_state, insert, now_iso, set_state

VARIANTS = ("real", "sombra_regra", "sombra_sem_macro")


def analyst_views(conn, day: date) -> dict:
    """Leitura resumida de cada analista da manhã (para medir concordância depois)."""
    row = conn.execute("SELECT dossier_json FROM b3_dossiers WHERE day=?", (day.isoformat(),)).fetchone()
    if not row:
        return {}
    a = json.loads(row["dossier_json"]).get("analysts", {})
    pick = lambda k, f: a.get(k, {}).get(f) if isinstance(a.get(k), dict) else None   # noqa: E731
    return {"macro": pick("macro", "risk_level"), "context": pick("context", "external_bias"),
            "flow": pick("flow", "aggression"), "tech": pick("tech", "regime"), "bull": pick("bull", "bias"),
            "bear": pick("bear", "bias")}


def plan_for(variant: str, conn, day: date) -> dict | None:
    if variant == "sombra_regra":
        return pl.rule_plan(day)
    p = pl.active_plan(conn, day.isoformat())
    if p and variant == "sombra_sem_macro":
        return {**p, "risk_level": "normal"}          # ablação: ignora o filtro de risco do macro
    return p


class Executor:
    def __init__(self, ctxs: dict[str, tb.B3Ctx], *, expiry_day: bool = False, entries_blocked: bool = False,
                 events_fn=lambda d: (), setup_status_fn=lambda ctx, setup: "NEUTRO", record_fn=None):
        self.ctxs = ctxs
        self.entries_blocked = entries_blocked        # dia bloqueado à mão em b3_calendar.yaml
        self.real = ctxs["real"]
        self.cfg = self.real.cfg
        self.expiry_day = expiry_day
        self.events_fn, self.setup_status_fn, self.record_fn = events_fn, setup_status_fn, record_fn
        self._seen: dict[tuple, str] = {}             # (variant, setup_id) -> última barra avaliada
        self._last_watch = self._last_record = 0.0
        self._regime: tuple[float, dict] | None = None
        self.flattened = False

    # ---------------------------------------------------------------- dados
    def market(self, now: datetime) -> dict:
        b = self.real.broker
        sym = self.real.symbol
        bars_1m = b.bars(sym, "1m", 1600)
        closed_1m = [x for x in bars_1m if x.time + timedelta(minutes=1) <= now]
        daily = b.bars(sym, "1d", 80)
        if self._regime is None or time.monotonic() - self._regime[0] > 900:
            self._regime = (time.monotonic(), b3_regime(daily, b.bars(sym, "60m", 120)))
        today = [x for x in closed_1m if x.time.date() == now.date()]
        a5 = ft.atr(resample(closed_1m, 5))
        return {"closed_1m": closed_1m, "today_1m": today, "levels": ft.levels(closed_1m, daily, now.date()),
                "atr5m": a5, "regime": self._regime[1], "tick": b.last_tick(sym)}

    @staticmethod
    def closed_tf(today_1m, tf: str, now: datetime):
        m = TF_MIN[tf]
        bars = resample(today_1m, m) if m > 1 else today_1m
        return [x for x in bars if x.time + timedelta(minutes=m) <= now]

    # ---------------------------------------------------------------- passo
    def step(self, now: datetime) -> dict:
        out = {"entries": [], "events": [], "watchdog": None}
        s = self.cfg["session"]
        if time.monotonic() - self._last_watch >= self.cfg["executor"]["watchdog_every_s"]:
            self._last_watch = time.monotonic()
            w = watchdog.run_once(self.real)
            out["watchdog"] = w["action"]
        if self.record_fn and time.monotonic() - self._last_record >= 15:
            self._last_record = time.monotonic()
            try:
                self.record_fn(now)
            except BrokerError as e:
                out["events"].append(f"recorder: {e}")
        if now.time() >= hhmm(s["flatten_at"]):
            if not self.flattened:
                for ctx in self.ctxs.values():
                    out["events"] += tb.flatten_all(ctx, "flatten")
                self.flattened = True
            return out
        m = self.market(now)
        for variant, ctx in self.ctxs.items():
            try:
                out["events"] += self._variant(ctx, variant, m, now, out)
            except (BrokerError, tb.TradeError) as e:
                out["events"].append(f"{variant}: {e}")
                if variant == "real" and isinstance(e, BrokerError):
                    self._last_watch = 0.0            # força o watchdog no próximo passo
        return out

    def _invalid_key(self, variant, now):
        return f"b3_invalidated:{variant}:{now.date().isoformat()}"

    def _variant(self, ctx: tb.B3Ctx, variant: str, m: dict, now: datetime, out: dict) -> list[str]:
        events = []
        r = tb.reconcile(ctx)
        events += [f"{variant}: {e}" for e in r["events"]]
        if r["divergences"] and variant == "real":
            self._last_watch = 0.0
            return events + r["divergences"]
        plan = plan_for(variant, ctx.conn, now.date())
        tick = float(self.cfg["instrument"]["tick_points"])
        invalid = set(get_state(ctx.conn, self._invalid_key(variant, now), []))
        setups = {x["id"]: x for x in (plan or {}).get("setups", [])}
        # invalidações do dia (valem para entrada e para a posição aberta do setup)
        for sid, x in setups.items():
            if sid in invalid or now.time() < hhmm(x["window"]["from"]):   # só vale depois que a janela abre
                continue
            for inv in x["invalidation"]:
                if pl.invalidated(inv, self.closed_tf(m["today_1m"], inv["timeframe"], now), m["levels"]):
                    invalid.add(sid)
                    events.append(f"{variant}: {sid} invalidado ({inv['type']})")
        set_state(ctx.conn, self._invalid_key(variant, now), sorted(invalid))
        # pedido de zeragem do operador (em papel a posição vive neste processo)
        if variant == "real" and get_state(ctx.conn, "b3_close_request"):
            req = get_state(ctx.conn, "b3_close_request")
            set_state(ctx.conn, "b3_close_request", None)
            for t in tb.open_trades(ctx):
                if t["status"] == "open":
                    tb.close_trade(ctx, t, "manual")
                    events.append(f"real: zerado a pedido do operador ({req.get('reason')})")
        # gerenciamento
        tk = m["tick"]
        for t in tb.open_trades(ctx):
            if t["status"] != "open":
                continue
            if t["setup_id"] in invalid or (plan and plan["risk_level"] == "fora"):
                tb.close_trade(ctx, t, "invalidation" if t["setup_id"] in invalid else "revisao")
                continue
            be = rk.breakeven_stop(t["side"], t["entry_price"], t["initial_sl"], t["sl"], tk.bid, tk.ask)
            if be is not None:
                try:
                    tb.move_stop(ctx, t, be, "+1R: stop na entrada")
                except tb.TradeError as e:
                    events.append(f"{variant}: breakeven recusado {e}")
        if not plan or self.entries_blocked:
            return events
        # entradas: no máximo uma por passo
        st = tb.day_state(ctx, plan)
        if st.open_position:
            return events
        events_today = tuple(self.events_fn(now.date()))
        for sid, x in setups.items():
            if not x["active"] or sid in invalid or not pl.in_window(x, now.time()):
                continue
            closed = self.closed_tf(m["today_1m"], x["trigger"]["timeframe"], now)
            if not closed:
                continue
            bar_key = closed[-1].time.isoformat()
            if self._seen.get((variant, sid)) == bar_key:
                continue
            self._seen[(variant, sid)] = bar_key
            if not pl.fired(x, closed, m["levels"], tick):
                continue
            entry = float(tk.ask if x["direction"] == "long" else tk.bid)
            stp = pl.stop_target(x, entry, m["levels"], m["atr5m"], tick)
            st.setup_status = self.setup_status_fn(ctx, x["setup"])
            detail = {"setup": x["setup"], "bar": bar_key, "trigger": x["trigger"], "levels": m["levels"],
                      "bid": float(tk.bid), "ask": float(tk.ask), "atr5m": m["atr5m"]}
            if stp is None:
                self._signal(ctx, variant, now, sid, bar_key, x["direction"], "rejected", "NO_LEVEL", detail)
                continue
            a = rk.check_entry(self.cfg, st, side=x["direction"], setup_id=sid, max_entries=x["max_entries"],
                               bid=tk.bid, ask=tk.ask, stop=stp[0], target=stp[1], atr5m=m["atr5m"], now=now,
                               expiry_day=self.expiry_day, events=events_today)
            if not a.ok:
                self._signal(ctx, variant, now, sid, bar_key, x["direction"], "rejected", a.code,
                             {**detail, "hint": a.hint, "stop": stp[0], "target": stp[1]})
                events.append(f"{variant}: {sid} sinal recusado {a.code}")
                continue
            self._signal(ctx, variant, now, sid, bar_key, x["direction"], "approved", None,
                         {**detail, "sl": str(a.sl), "tp": str(a.tp)})
            try:
                t = tb.enter(ctx, a, setup=x["setup"], setup_id=sid, plan=plan,
                             context={"regime": m["regime"].get("daily"), "regime_full": m["regime"],
                                      "trigger_level": pl.ref_price(x["trigger"], m["levels"]), "bar": bar_key,
                                      "analysts": analyst_views(ctx.conn, now.date())})
                out["entries"].append({"variant": variant, "setup_id": sid, "trade_id": t["id"]})
            except tb.TradeError as e:
                self._signal(ctx, variant, now, sid, bar_key + "#err", x["direction"], "error", e.code, {"hint": e.hint})
                events.append(f"{variant}: entrada {sid} falhou {e}")
            break
        return events

    def _signal(self, ctx, variant, now, sid, bar_key, side, decision, code, detail):
        try:
            insert(ctx.conn, "b3_signals", {"ts": now_iso(), "day": now.date().isoformat(), "variant": variant,
                                            "setup_id": sid, "bar_time": bar_key, "side": side, "decision": decision,
                                            "code": code, "detail_json": json.dumps(detail, default=str)[:4000]})
        except Exception:  # noqa: BLE001 — sinal repetido (UNIQUE) não interrompe o loop
            pass


def build(cfg, conn, broker, symbol: str, notify, now_fn=None) -> Executor:
    from trader.b3.runtime import expiry_today, make_ctx
    ctxs = {v: make_ctx(cfg, conn, broker, symbol, notify=notify, variant=v, now=now_fn) for v in VARIANTS}
    for c in ctxs.values():
        if c.broker.is_paper:
            tb.restore_paper(c)
    from trader.analytics import setup_status
    from trader.b3 import calendar
    from trader.collectors.recorder import record
    now = (now_fn or ctxs["real"].now)()
    return Executor(ctxs, expiry_day=expiry_today(cfg, broker, now.date()), entries_blocked=calendar.blocked(now.date()),
                    events_fn=calendar.high_impact_times,
                    setup_status_fn=setup_status,
                    record_fn=lambda t: record(conn, broker, symbol, t, book=True))


def main(argv: list[str]) -> int:
    from trader.b3.config import load_b3
    from trader.b3.runtime import connect_broker, preflight
    from trader.config import load_secrets
    from trader.db import connect
    from trader.lock import exclusive
    from trader.notify import notify
    cfg, conn, secrets = load_b3(), connect(), load_secrets()
    say = lambda m: notify(m, secrets)   # noqa: E731
    try:
        with exclusive("b3_executor"):
            broker = connect_broker(cfg)
            pf = preflight(cfg, conn, broker)
            print(json.dumps(pf, ensure_ascii=False, default=str))
            if pf["status"] == "ABORT":
                say("❗ B3 executor não iniciou: " + "; ".join(pf["problems"]))
                return 1
            ex = build(cfg, conn, broker, pf["contract"]["symbol"], say)
            if pf["status"] == "MANAGE_ONLY":
                say("⚠️ B3 executor só gerencia hoje: " + "; ".join(pf["entries_blocked"]))
            say(f"▶️ B3 executor ligado ({cfg['mode']}, {pf['contract']['symbol']})")
            end = datetime.combine(date.today(), hhmm(cfg["session"]["flatten_at"]), tb.TZ) + timedelta(minutes=5)
            while datetime.now(tb.TZ) < end:
                r = ex.step(datetime.now(tb.TZ))
                for e in r["events"]:
                    print(e)
                time.sleep(cfg["executor"]["poll_seconds"])
            from trader.analytics import day_summary
            say("⏹️ B3 executor encerrado (fim do pregão)\n" + day_summary(conn, date.today().isoformat()))
            return 0
    except BlockingIOError:
        print("outro executor B3 rodando; saindo")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
