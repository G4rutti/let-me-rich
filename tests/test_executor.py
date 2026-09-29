from datetime import date, time

from b3_data import day, ramp
from test_plan import plan as _plan, setup as _setup
from test_risk_b3 import cfg
from trader import plan as pl
from trader.b3.runtime import make_ctx
from trader.broker.sim import Replay
from trader.db import connect
from trader.executor import VARIANTS, Executor

D0, D1 = date(2026, 9, 30), date(2026, 10, 1)


def setup(*a, **kw):
    return _setup(*a, **{"invalidation": [], **kw})


def plan(**kw):
    return _plan(**{"setups": [setup()], **kw})


def zigzag(lo, hi, n, period=10):
    half = period // 2
    return [lo + (hi - lo) * (i % period if i % period < half else period - i % period) / half for i in range(n)]


def session(after: list[float], until_minutes=None):
    """Pregão de ontem em zigue-zague (ATR5m ~100) + hoje: range de abertura, rompimento às 09:40 e `after`."""
    prev = day(D0, [round(x / 5) * 5 for x in zigzag(129900, 130100, 480)])
    today = [round(x / 5) * 5 for x in zigzag(129950, 130100, 30)] + [130050] * 10 + ramp(130050, 130200, 5)[1:] + [130200]
    today += after
    if until_minutes:
        today += [today[-1]] * (until_minutes - len(today))
    return prev, day(D1, today)


def run(plan_raw, after, until=None, stop_at=None, c=None):
    prev, today = session(after, until)
    rp = Replay(prev + today, "WINV26")
    rp.i = len(prev) - 1
    conn = connect(":memory:")
    c = c or cfg("dry")
    if plan_raw:
        pl.save_plan(conn, pl.validate_plan(plan_raw, c, D1), "plan")
    ctxs = {v: make_ctx(c, conn, rp, "WINV26", notify=lambda m: None, variant=v, now=lambda: rp.now) for v in VARIANTS}
    for x in ctxs.values():
        x.sleep = lambda s: None
    ex = Executor(ctxs)
    entries = []
    while rp.advance():
        now = rp.now
        if stop_at and now.time() > stop_at:
            break
        r = ex.step(now)
        entries += [(now.time(), e["variant"], e["setup_id"]) for e in r["entries"]]
    return conn, entries


def trades(conn, variant="real"):
    return [dict(r) for r in conn.execute("SELECT * FROM b3_trades WHERE variant=? ORDER BY id", (variant,))]


def test_entra_no_fechamento_da_barra_e_sai_no_alvo():
    conn, entries = run(plan(), ramp(130200, 130600, 30) + [130600] * 20)
    real = [e for e in entries if e[1] == "real"]
    assert real == [(time(9, 45), "real", "s1")]                   # barra 5m das 09:40 fechou acima do or30_high
    t = trades(conn)[0]
    assert t["mode"] == "dry" and t["side"] == "long" and t["status"] == "closed" and t["exit_reason"] == "target"
    assert t["r_multiple"] > 1.5
    assert trades(conn, "sombra_sem_macro")[0]["exit_reason"] == "target"
    sig = conn.execute("SELECT bar_time, decision FROM b3_signals WHERE variant='real'").fetchall()
    assert [(s["bar_time"][11:16], s["decision"]) for s in sig] == [("09:40", "approved")]


def test_stop_move_para_entrada_com_1r_e_sai_no_zero():
    after = ramp(130200, 130320, 8) + ramp(130320, 130150, 10) + [130150] * 10
    conn, _ = run(plan(), after)
    t = trades(conn)[0]
    assert t["sl"] == t["entry_price"] and t["exit_reason"] == "breakeven"


def test_uma_posicao_por_vez():
    p = plan(setups=[setup(), setup("s2", trigger={"type": "close_above", "level_ref": "day_open"})])
    conn, entries = run(p, [130200] * 30)
    assert len([e for e in entries if e[1] == "real"]) == 1


def test_invalidacao_bloqueia_entrada():
    p = plan(setups=[setup(invalidation=[{"type": "price_below", "price": 130060, "timeframe": "5m"}])])
    conn, entries = run(p, ramp(130200, 130600, 30))
    assert not [e for e in entries if e[1] == "real"] and not trades(conn)


def test_risk_level_fora_nao_entra_mas_sombra_sem_macro_sim():
    conn, entries = run(plan(risk_level="fora"), ramp(130200, 130600, 30))
    assert not trades(conn)
    assert trades(conn, "sombra_sem_macro")
    rej = conn.execute("SELECT code FROM b3_signals WHERE variant='real'").fetchone()
    assert rej["code"] == "RISK_FORA"


def test_sem_plano_nao_opera():
    conn, entries = run(None, ramp(130200, 130600, 30))
    assert not trades(conn) and not trades(conn, "sombra_sem_macro")


def test_zeragem_por_horario():
    p = plan(setups=[setup(target={"type": "r_multiple", "value": 5.0})])
    conn, _ = run(p, [130200] * 10, until=8 * 60 + 35)
    t = trades(conn)[0]
    assert t["exit_reason"] == "flatten" and t["closed_at"]
