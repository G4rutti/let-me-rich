from datetime import datetime, timedelta
from decimal import Decimal as Dec
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from trader import risk_b3 as rk
from trader.b3.config import load_b3

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=TZ)


def cfg(mode="dry", **risk):
    c = load_b3()
    d = {k: (dict(v) if hasattr(v, "keys") else v) for k, v in c.items()}
    d["mode"] = mode
    d["risk"].update(risk)
    return d


# long: ask 130000, stop 100 pts abaixo, alvo 2R; short espelhado
LONG = dict(side="long", setup_id="s1", max_entries=1, bid=129995, ask=130000, stop=129900, target=130200, atr5m=100)
SHORT = dict(side="short", setup_id="s1", max_entries=1, bid=130000, ask=130005, stop=130100, target=129800, atr5m=100)


def entry(c=None, st=None, **kw):
    base = LONG if kw.get("side", "long") == "long" else SHORT
    return rk.check_entry(c or cfg(), st or rk.DayState(), **{**base, **kw, "now": kw.get("now", NOW)})


@pytest.mark.parametrize("base", [LONG, SHORT])
def test_aprova_long_e_short(base):
    a = entry(**base)
    assert a.ok and a.contracts == 1 and a.side == base["side"]
    assert a.stop_points == 100 and a.risk_brl == Dec("23.0")    # 100 pts x 0,20 + custo 3
    if base["side"] == "long":
        assert (a.entry, a.sl, a.tp) == (130000, 129900, 130200)
    else:
        assert (a.entry, a.sl, a.tp) == (130000, 130100, 129800)


def test_arredonda_stop_para_longe_e_alvo_para_perto():
    a = entry(stop=129903, target=130203)
    assert a.sl == 129900 and a.tp == 130200
    a = entry(**{**SHORT, "stop": 130097, "target": 129797})
    assert a.sl == 130100 and a.tp == 129800


@pytest.mark.parametrize("base,kw,code", [
    (LONG, {"stop": 130010}, "STOP_WRONG_SIDE"),
    (SHORT, {"stop": 129990}, "STOP_WRONG_SIDE"),
    (LONG, {"target": 129990}, "TARGET_WRONG_SIDE"),
    (SHORT, {"target": 130010}, "TARGET_WRONG_SIDE"),
    (LONG, {"stop": 129950}, "STOP_TOO_TIGHT"),
    (SHORT, {"stop": 130050}, "STOP_TOO_TIGHT"),
    (LONG, {"stop": 129860, "target": 130300, "atr5m": 200}, "STOP_TOO_WIDE"),
    (SHORT, {"stop": 130140, "target": 129700, "atr5m": 200}, "STOP_TOO_WIDE"),
    (LONG, {"atr5m": 60}, "STOP_TOO_WIDE_ATR"),
    (SHORT, {"atr5m": None}, "NO_ATR"),
    (LONG, {"target": 130100}, "RR_TOO_LOW"),
    (SHORT, {"target": 129900}, "RR_TOO_LOW"),
    (LONG, {"ask": 130015}, "SPREAD"),
    (LONG, {"bid": 0}, "BAD_PRICE"),
    (LONG, {"now": NOW.replace(hour=9, minute=10)}, "OUTSIDE_WINDOW"),
    (SHORT, {"now": NOW.replace(hour=16, minute=30)}, "OUTSIDE_WINDOW"),
    (LONG, {"expiry_day": True}, "EXPIRY_DAY"),
    (SHORT, {"events": (NOW + timedelta(minutes=20),)}, "EVENT_WINDOW"),
])
def test_recusas_com_codigo(base, kw, code):
    r = entry(**{**base, **kw})
    assert not r.ok and r.code == code, r


def test_evento_fora_da_janela_passa():
    assert entry(events=(NOW + timedelta(minutes=45),)).ok


def test_tamanho_zero_recusa_e_teto_1():
    # custo alto: (30 - 25) / (100 x 0,2) = 0 contratos -> recusa, nunca aumenta
    c = cfg(costs_per_contract_brl=23.0)
    r = entry(c, target=130400)
    assert r.code == "SIZE_ZERO"
    # stop pequeno daria 2 contratos -> usa 1
    a = entry(cfg(stop_min_points=10), stop=129950, target=130100, atr5m=100)
    assert a.ok and a.contracts == 1


def test_custos_comem_o_alvo():
    c = cfg(stop_min_points=10, min_rr=1)
    r = entry(c, stop=129960, target=130040, atr5m=100)    # alvo vale R$8 < 3 x R$3
    assert r.code == "COSTS_EAT_TARGET"


@pytest.mark.parametrize("st,code", [
    (rk.DayState(paused=True), "PAUSED"),
    (rk.DayState(consecutive_order_failures=3), "CIRCUIT_BREAKER"),
    (rk.DayState(realized_today_brl=Dec(-30)), "DAILY_LOSS_HIT"),
    (rk.DayState(realized_today_brl=Dec(-10), open_pnl_brl=Dec(-20)), "DAILY_LOSS_HIT"),
    (rk.DayState(total_pnl_brl=Dec(-60)), "TOTAL_LOSS_HIT"),
    (rk.DayState(halted_today=True), "DAILY_LOSS_HIT"),
    (rk.DayState(open_position=True), "OPEN_POSITION"),
    (rk.DayState(trades_today=2), "MAX_TRADES_DAY"),
    (rk.DayState(risk_level="reduzido", bias="long", trades_today=1), "MAX_TRADES_DAY"),
    (rk.DayState(risk_level="fora"), "RISK_FORA"),
    (rk.DayState(last_stop_at=NOW - timedelta(minutes=10)), "COOLDOWN"),
    (rk.DayState(entries_by_setup={"s1": 1}), "MAX_ENTRIES_SETUP"),
    (rk.DayState(setup_status="EVITAR"), "SETUP_AVOID"),
    (rk.DayState(realized_today_brl=Dec(-10)), "DAILY_RISK_LEFT"),   # resta 20 < risco 23
    (rk.DayState(total_pnl_brl=Dec(-40)), "TOTAL_RISK_LEFT"),         # resta 20 < 23
])
def test_travas_de_estado(st, code):
    r = entry(st=st)
    assert r.code == code, r


def test_mode_off():
    assert entry(cfg("off")).code == "MODE_OFF"


def test_cooldown_expira():
    assert entry(st=rk.DayState(last_stop_at=NOW - timedelta(minutes=31))).ok


def test_dia_reduzido():
    st = rk.DayState(risk_level="reduzido", bias="short")
    assert entry(st=st).code == "AGAINST_BIAS"
    assert entry(st=st, **SHORT).ok
    r = entry(st=st, **{**SHORT, "stop": 130120, "target": 129700, "atr5m": 200})
    assert r.code == "STOP_TOO_WIDE" and "reduzido" in r.hint                 # 120 > 100 do reduced_day
    st.bias = "neutral"
    assert entry(st=st, **SHORT).code == "AGAINST_BIAS"


def test_loss_action():
    c = cfg()
    assert rk.loss_action(c, rk.DayState()) is None
    assert rk.loss_action(c, rk.DayState(realized_today_brl=Dec(-15), open_pnl_brl=Dec(-15))) == "day"
    assert rk.loss_action(c, rk.DayState(total_pnl_brl=Dec(-61))) == "total"


def test_move_stop_so_a_favor():
    c = cfg()
    assert rk.check_move_stop(c, "long", 129900, 130000, 130100, 130105) == 130000
    assert rk.check_move_stop(c, "long", 129900, 129850, 130100, 130105).code == "STOP_ONLY_FAVOR"
    assert rk.check_move_stop(c, "long", 129900, 130100, 130100, 130105).code == "STOP_BEYOND_PRICE"
    assert rk.check_move_stop(c, "short", 130100, 130000, 129895, 129900) == 130000
    assert rk.check_move_stop(c, "short", 130100, 130200, 129895, 129900).code == "STOP_ONLY_FAVOR"
    assert rk.check_move_stop(c, "short", 130100, 129900, 129895, 129900).code == "STOP_BEYOND_PRICE"


def test_breakeven():
    assert rk.breakeven_stop("long", 130000, 129900, 129900, 130100, 130105) == 130000
    assert rk.breakeven_stop("long", 130000, 129900, 129900, 130095, 130100) is None
    assert rk.breakeven_stop("long", 130000, 129900, 130000, 130200, 130205) is None   # já no zero
    assert rk.breakeven_stop("short", 130000, 130100, 130100, 129895, 129900) == 130000


def test_pnl():
    c = cfg()
    assert rk.pnl_brl(c, "long", 130000, 129900) == Dec("-21.0")
    assert rk.pnl_brl(c, "short", 130000, 129800) == Dec("39.0")


def test_send_allowed():
    real = SimpleNamespace(is_real=True, number=42)
    c = cfg("live")
    c["account_number"] = 42
    assert rk.send_allowed(c, real)[0]
    assert not rk.send_allowed(c, SimpleNamespace(is_real=False, number=42))[0]
    assert not rk.send_allowed(c, SimpleNamespace(is_real=True, number=7))[0]
    assert not rk.send_allowed(cfg("dry"), real)[0]
    assert not rk.send_allowed(c, None)[0]
