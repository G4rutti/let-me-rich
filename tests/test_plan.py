import copy
from datetime import date

import pytest

from b3_data import day, ramp
from test_risk_b3 import cfg
from trader import plan as pl
from trader.db import connect

D1 = date(2026, 10, 1)


def setup(sid="s1", direction="long", **kw):
    s = {"id": sid, "setup": "opening_range_breakout", "direction": direction,
         "trigger": {"type": "close_above" if direction == "long" else "close_below", "timeframe": "5m",
                     "level_ref": "or30_high" if direction == "long" else "or30_low"},
         "window": {"from": "09:30", "to": "11:30"},
         "stop": {"type": "points", "value": 100},
         "target": {"type": "r_multiple", "value": 2.0},
         "invalidation": [{"type": "price_below" if direction == "long" else "price_above", "level_ref": "vwap"}],
         "max_entries": 1, "bull_case": "rompimento com volume",
         "bear_review": {"verdict": "OK", "strength": 2, "points": ["gap grande"]}}
    s.update(kw)
    return s


def plan(**kw):
    p = {"date": "2026-10-01", "bias": "long", "risk_level": "normal", "summary": "exterior positivo",
         "levels": [{"name": "maxima_ontem", "price": 131250}, {"name": "vwap", "ref": "vwap"}],
         "setups": [setup()]}
    p.update(kw)
    return p


def ok(p, c=None):
    return pl.validate_plan(p, c or cfg(), D1)


def err(p, code, c=None):
    with pytest.raises(pl.PlanError) as e:
        ok(p, c)
    assert e.value.code == code, e.value
    return e.value


def test_plano_valido_normaliza():
    p = ok(plan())
    assert p["setups"][0]["window"] == {"from": "09:30", "to": "11:30"} and p["setups"][0]["active"] is True


@pytest.mark.parametrize("mut", [
    lambda p: p["setups"][0]["trigger"].update(type="expr_livre"),
    lambda p: p["setups"][0]["trigger"].update(level_ref="qualquer_coisa"),
    lambda p: p["setups"][0]["trigger"].update(price=130000),                 # level_ref E price
    lambda p: p["setups"][0].update(extra="x"),
    lambda p: p["setups"][0].pop("bear_review"),
    lambda p: p.update(bias="all_in"),
    lambda p: p["setups"][0]["stop"].update(type="level"),                    # level sem referência
    lambda p: p["setups"][0].update(max_entries=5),
])
def test_schema_fechado(mut):
    p = plan()
    mut(p)
    err(p, "SCHEMA")


def test_regras():
    err(plan(date="2026-10-02"), "WRONG_DATE")
    err(plan(setups=[setup(window={"from": "09:00", "to": "10:00"})]), "BAD_WINDOW")
    err(plan(setups=[setup(), setup()]), "DUPLICATE_ID")
    err(plan(setups=[setup(bear_review={"verdict": "SEM_VETO", "strength": 4})]), "BEAR_VETO")
    err(plan(setups=[setup(bear_review={"verdict": "VETO", "strength": 3})]), "BEAR_VETO")
    assert ok(plan(setups=[setup(bear_review={"verdict": "OK", "strength": 3})]))
    err(plan(setups=[setup(stop={"type": "points", "value": 200})]), "STOP_POINTS")
    err(plan(setups=[setup(stop={"type": "atr", "value": 3})]), "STOP_ATR")
    err(plan(setups=[setup(target={"type": "r_multiple", "value": 1.2})]), "RR_TOO_LOW")


def test_dia_reduzido_so_a_favor_do_bias():
    err(plan(risk_level="reduzido", bias="short"), "AGAINST_BIAS")
    err(plan(risk_level="reduzido", setups=[setup(stop={"type": "points", "value": 120})]), "STOP_POINTS")
    assert ok(plan(risk_level="reduzido"))


def test_revisao_so_reduz_risco():
    old = ok(plan(setups=[setup(), setup("s2", "short", active=True)], bias="long"))
    rev = lambda **kw: pl.validate_revision(old, plan(**kw), cfg(), D1)  # noqa: E731
    # permitido
    assert rev(setups=[setup(), setup("s2", "short", active=False)])
    assert rev(setups=[setup(window={"from": "10:00", "to": "11:00"})])
    assert rev(setups=[setup(stop={"type": "points", "value": 80})], risk_level="normal")
    assert rev(setups=[setup(), setup("s3", "long")])                          # novo com bear_review
    assert rev(risk_level="fora", bias="neutral")
    # recusado
    for kw in ({"risk_level": "normal", "setups": [setup(window={"from": "09:30", "to": "12:00"})]},
               {"setups": [setup(stop={"type": "points", "value": 120})]},
               {"setups": [setup(max_entries=2)]},
               {"setups": [setup(invalidation=[])]},
               {"setups": [setup(target={"type": "r_multiple", "value": 3})]},
               {"setups": [setup(direction="short", trigger={"type": "close_below", "level_ref": "or30_low"})]},
               {"bias": "short"}):
        with pytest.raises(pl.PlanError, match="REVISION_ADDS_RISK"):
            rev(**kw)
    red = pl.validate_revision(old, plan(risk_level="reduzido", setups=[setup()]), cfg(), D1)
    with pytest.raises(pl.PlanError, match="REVISION_ADDS_RISK"):
        pl.validate_revision(red, plan(risk_level="normal"), cfg(), D1)
    off = copy.deepcopy(old)
    off["setups"][1]["active"] = False
    with pytest.raises(pl.PlanError, match="não volta"):
        pl.validate_revision(off, plan(setups=[setup(), setup("s2", "short")]), cfg(), D1)


def test_versoes():
    conn = connect(":memory:")
    assert pl.active_plan(conn, "2026-10-01") is None
    assert pl.save_plan(conn, ok(plan()), "plan") == 1
    assert pl.save_plan(conn, ok(plan(risk_level="reduzido")), "revise") == 2
    p = pl.active_plan(conn, "2026-10-01")
    assert p["version"] == 2 and p["risk_level"] == "reduzido"


# ------------------------------------------------------------ gatilhos

def bars(path):
    return day(D1, path, wick=0)


L = {"or30_high": 130100.0, "or30_low": 129900.0, "vwap": 130000.0}


@pytest.mark.parametrize("typ,direction,path,expected", [
    ("close_above", "long", [130050, 130150], True),
    ("close_above", "long", [130150, 130200], False),          # já estava acima: não é rompimento
    ("close_below", "short", [129950, 129850], True),
    ("touch_and_reject", "long", [130200, 130150], False),
    ("touch_and_reject", "short", [130000, 130080], False),
])
def test_gatilhos_simples(typ, direction, path, expected):
    s = setup(direction=direction, trigger={"type": typ, "level_ref": "or30_high" if direction == "long" else "or30_low"})
    assert pl.fired(s, bars(path), L, 5) is expected


def test_touch_and_reject_long():
    from decimal import Decimal as Dec
    from trader.broker.base import Bar
    b = bars([130200, 130200])
    b[-1] = Bar(b[-1].time, Dec(130110), Dec(130160), Dec(130090), Dec(130150), Dec(1))   # furou e fechou acima
    s = setup(trigger={"type": "touch_and_reject", "level_ref": "or30_high"})
    assert pl.fired(s, b, L, 5)


def test_pullback_e_break_and_retest():
    pb = setup(trigger={"type": "pullback_to", "level_ref": "vwap"})
    path = [130100, 130090, 130080, 130060]
    b = bars(path)
    from decimal import Decimal as Dec
    from trader.broker.base import Bar
    b.append(Bar(b[-1].time.replace(minute=4), Dec(130030), Dec(130060), Dec(129995), Dec(130050), Dec(1)))
    assert pl.fired(pb, b, L, 5)
    br = setup(trigger={"type": "break_and_retest", "level_ref": "or30_high"})
    path = [130000, 130050, 130150, 130200, 130180]
    b = bars(path)
    b.append(Bar(b[-1].time.replace(minute=5), Dec(130150), Dec(130160), Dec(130095), Dec(130140), Dec(1)))
    assert pl.fired(br, b, L, 5)
    assert not pl.fired(br, bars([130000, 130050, 130060, 130070]), L, 5)


def test_invalidacao_stop_e_alvo():
    assert pl.invalidated({"type": "price_below", "level_ref": "vwap"}, bars([129990]), L)
    assert not pl.invalidated({"type": "price_below", "level_ref": "vwap"}, bars([130010]), L)
    assert not pl.invalidated({"type": "price_below", "level_ref": "pdh"}, bars([1]), L)       # nível inexistente
    s = setup(stop={"type": "level", "level_ref": "or30_low", "offset_ticks": 2})
    assert pl.stop_target(s, 130100, L, 80, 5) == (129890, 130100 + 2 * 210)
    s = setup(direction="short", stop={"type": "atr", "value": 1.0}, target={"type": "level", "level_ref": "or30_low"})
    assert pl.stop_target(s, 130000, L, 80, 5) == (130080, 129900)
    assert pl.stop_target(s, 130000, L, None, 5) is None


def test_plano_da_regra_e_valido():
    assert ok({k: v for k, v in pl.rule_plan(D1).items() if k != "version"})
    assert ramp(0, 10, 3) == [0, 5, 10]


def test_revisao_reabre_o_dia_ate_o_teto_do_macro():
    fora = ok(plan(risk_level="fora", bias="neutral", setups=[]))
    novo = plan(risk_level="normal", bias="short", setups=[setup("s1", "short")])
    assert pl.validate_revision(fora, novo, cfg(), D1, risk_cap="normal")["risk_level"] == "normal"
    assert pl.validate_revision(fora, plan(risk_level="reduzido", bias="short", setups=[setup("s1", "short")]),
                                cfg(), D1, risk_cap="normal")
    with pytest.raises(pl.PlanError, match="teto"):
        pl.validate_revision(fora, novo, cfg(), D1, risk_cap="reduzido")
    with pytest.raises(pl.PlanError, match="teto"):
        pl.validate_revision(fora, novo, cfg(), D1, risk_cap=None)          # sem macro não reabre
    normal = ok(plan(bias="long"))
    with pytest.raises(pl.PlanError, match="só pode virar neutral"):
        pl.validate_revision(normal, plan(bias="short"), cfg(), D1, risk_cap="normal")
