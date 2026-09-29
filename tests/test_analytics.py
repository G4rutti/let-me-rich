import json
from types import SimpleNamespace

from test_plan import D1, ok, plan
from trader import analytics as an
from trader.db import connect
from trader.plan import save_plan
from trader.telegram_daemon import cmd_plano, plan_text


def add(conn, variant="real", setup="orb", side="long", r=1.0, pnl=20.0, hour=10, views=None, regime="alta", n=1):
    for _ in range(n):
        conn.execute(
            "INSERT INTO b3_trades (variant, mode, day, symbol, setup, setup_id, side, status, contracts, signal_price, "
            "initial_sl, sl, tp, risk_brl, created_at, opened_at, closed_at, pnl_brl, r_multiple, slippage_points, "
            "risk_level, bias, regime, context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (variant, "dry", "2026-10-01", "WINV26", setup, "s1", side, "closed", 1, 1, 1, 1, 1, 23,
             f"2026-10-01T{hour + 3:02d}:00:00+00:00", f"2026-10-01T{hour + 3:02d}:00:00+00:00",
             f"2026-10-01T{hour + 3:02d}:30:00+00:00", pnl, r, 5, "normal", "long", regime,
             json.dumps({"analysts": views or {}})))


def test_cortes_e_concordancia():
    conn = connect(":memory:")
    add(conn, r=2, pnl=40, hour=9, views={"macro": "normal", "context": "positivo"})
    add(conn, r=-1, pnl=-23, hour=14, side="short", views={"context": "positivo"}, regime="baixa")
    rows = an.closed(conn)
    assert an.stats(rows) == {"n": 2, "win_rate": 0.5, "expectancy_r": 0.5, "expectancy_brl": 8.5, "pnl_brl": 17.0,
                              "max_drawdown_brl": -23.0, "avg_slippage_points": 5.0}
    assert set(an.cut(rows, "hour")) == {"09h", "14h"}
    assert an.cut(rows, "agree_context") == {"concorda": an.stats(rows[:1]), "discorda": an.stats(rows[1:])}
    assert set(an.cut(rows, "agree_macro")) == {"sem_leitura"}
    assert set(an.cut(rows, "regime")) == {"alta", "baixa"}
    rep = an.report(conn, days=None)
    assert rep["real"]["n"] == 2 and "agree_bull" in rep["by"]


def test_status_do_setup():
    conn = connect(":memory:")
    ctx = SimpleNamespace(conn=conn, variant="real")
    add(conn, setup="ruim", r=-1, pnl=-23, n=9)
    assert an.setup_status(ctx, "ruim") == "NEUTRO"          # amostra pequena
    add(conn, setup="ruim", r=-1, pnl=-23)
    assert an.setup_status(ctx, "ruim") == "EVITAR"
    add(conn, setup="bom", r=1, pnl=20, n=10)
    assert an.setup_table(conn)["bom"]["status"] == "PROCURAR"


def test_ablacao_sugere_desligar_so_com_amostra():
    conn = connect(":memory:")
    add(conn, r=0.1, n=29)
    add(conn, variant="sombra_regra", r=0.5, n=30)
    add(conn, variant="sombra_sem_macro", r=0.5, n=30)
    assert an.ablation(conn)["notes"] == []
    add(conn, r=0.1)
    notes = an.ablation(conn)["notes"]
    assert len(notes) == 2 and "LLM" in notes[0] and "macro" in notes[1]


def test_resumo_do_dia_e_plano_no_telegram():
    conn = connect(":memory:")
    assert "nenhum trade" in an.day_summary(conn, "2026-10-01")
    add(conn, pnl=40)
    add(conn, variant="sombra_regra", pnl=-23)
    s = an.day_summary(conn, "2026-10-01")
    assert "real: 1 trade(s) R$40.00" in s and "sombra_regra" in s
    assert "sem plano" in plan_text(None)
    save_plan(conn, ok(plan()), "plan")
    from trader.plan import active_plan
    t = plan_text(active_plan(conn, D1.isoformat()))
    assert "v1" in t and "s1 opening_range_breakout long close_above or30_high" in t
    assert "sem plano" in cmd_plano(SimpleNamespace(conn=connect(":memory:")))
