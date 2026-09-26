"""Cobre todas as regras do risk manager, com precisão e min notional reais da Binance (fixtures)."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest
import yaml

from trader.config import CONFIG_DIR
from trader.risk import (Position, RiskState, check_entry, check_move_stop, check_new_target, check_partial,
                         day_start)

NOW = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)


def cfg(**over):
    c = yaml.safe_load((CONFIG_DIR / "risk.yaml").read_text(encoding="utf-8"))
    c["mode"] = "live"
    for k, v in over.items():
        c[k] = v
    return c


def state(**over):
    s = RiskState(equity_usd=Dec(90), free_usdt=Dec(90), day_start_equity=Dec(90))
    for k, v in over.items():
        setattr(s, k, v)
    return s


BTC = dict(category="major", ask=65000, stop=62400, target=70200, atr=1500)   # stop ~4%, alvo ~8%
PEPE = dict(category="meme", ask="0.00001000", stop="0.00000900", target="0.00001250", atr="0.0000005")


def entry(rules, c=None, s=None, sym="BTC/USDT", **kw):
    args = dict(BTC if sym == "BTC/USDT" else PEPE)
    args.update(kw)
    return check_entry(c or cfg(), s or state(), rules[sym], now=NOW, **args)


# ---------- caminho feliz e sizing ----------

def test_btc_approved_and_sized_by_risk(rules):
    r = entry(rules)
    assert r.ok, r
    assert r.risk_usd <= Dec(90) * Dec("0.015")          # nunca arrisca mais que 1,5% (major)
    assert r.risk_usd > Dec(90) * Dec("0.013")           # e usa quase todo o risco disponível
    assert r.qty == rules["BTC/USDT"].floor_qty(r.qty)   # respeita stepSize
    assert r.limit_price % rules["BTC/USDT"].tick == 0
    assert r.stop < r.limit_price < r.target
    assert r.notional >= Dec(5) * Dec("1.5")


def test_pepe_meme_real_precision_and_exposure_cap(rules):
    r = entry(rules, sym="PEPE/USDT")
    assert r.ok, r
    assert r.qty == r.qty.to_integral_value()            # PEPE step = 1
    assert r.notional <= Dec(9)                          # exposição meme 10% de 90
    assert r.risk_usd <= Dec(90) * Dec("0.005")


def test_caps_shrink_never_grow(rules):
    r = entry(rules, c=cfg(max_order_usd=10))
    assert r.ok and r.notional <= 10
    r = entry(rules, s=state(free_usdt=Dec(12)))
    assert r.ok and r.notional <= Dec(12) * Dec("0.99")
    r = entry(rules, c=cfg(max_position_pct=10))
    assert r.ok and r.notional <= 9


def test_below_min_notional_rejects_instead_of_bumping(rules):
    r = entry(rules, s=state(equity_usd=Dec(10), free_usdt=Dec(10), day_start_equity=Dec(10)))
    assert r.code == "BELOW_MIN_NOTIONAL"


def test_meme_exposure_full(rules):
    s = state(positions=[Position("DOGE/USDT", "meme", Dec("8.5"))])
    r = entry(rules, s=s, sym="PEPE/USDT")
    assert r.code == "BELOW_MIN_NOTIONAL" and "exposicao_meme" in r.hint


def test_daily_notional_cap(rules):
    assert entry(rules, s=state(notional_today=Dec(149))).code == "BELOW_MIN_NOTIONAL"


# ---------- travas globais ----------

@pytest.mark.parametrize("over,code", [
    ({"paused": True}, "PAUSED"),
    ({"consecutive_order_failures": 3}, "CIRCUIT_BREAKER"),
    ({"realized_today": Dec("-3.6")}, "DAILY_LOSS_HIT"),
    ({"trades_today": 4}, "MAX_TRADES_DAY"),
    ({"setup_status": "EVITAR"}, "SETUP_AVOID"),
])
def test_global_locks(rules, over, code):
    assert entry(rules, s=state(**over)).code == code


def test_mode_off(rules):
    assert entry(rules, c=cfg(mode="off")).code == "MODE_OFF"


def test_daily_loss_just_below_limit_passes(rules):
    assert entry(rules, s=state(realized_today=Dec("-3.5"))).ok


def test_stoploss_guard_and_expiry(rules):
    stops = [NOW - timedelta(hours=h) for h in (1, 2, 3)]
    assert entry(rules, s=state(recent_stops=stops)).code == "STOPLOSS_GUARD"
    old = [NOW - timedelta(hours=h) for h in (13, 14, 15)]          # pausa de 12h já passou
    assert entry(rules, s=state(recent_stops=old)).ok
    assert entry(rules, s=state(recent_stops=stops[:2])).ok          # só 2 stops


def test_cooldown_per_symbol(rules):
    s = state(last_stop_at={"BTC/USDT": NOW - timedelta(hours=2)})
    assert entry(rules, s=s).code == "COOLDOWN"
    s = state(last_stop_at={"BTC/USDT": NOW - timedelta(hours=13)})
    assert entry(rules, s=s).ok
    s = state(last_stop_at={"ETH/USDT": NOW - timedelta(hours=1)})
    assert entry(rules, s=s).ok


def test_positions_limits(rules):
    s = state(positions=[Position("BTC/USDT", "major", Dec(20))])
    assert entry(rules, s=s).code == "DUPLICATE_POSITION"
    s = state(positions=[Position(f"X{i}/USDT", "alt", Dec(5)) for i in range(3)])
    assert entry(rules, s=s).code == "MAX_POSITIONS"


def test_regime_bear(rules):
    assert entry(rules, s=state(regime="BEAR")).code == "REGIME_BEAR"
    assert entry(rules, s=state(regime="BEAR"), sym="PEPE/USDT").code == "REGIME_BEAR"
    c = cfg(bear_blocks={"major": False, "alt": True, "meme": True})
    assert entry(rules, c=c, s=state(regime="BEAR")).ok


def test_market_flags(rules):
    r = dict(rules)
    r["BTC/USDT"] = replace(rules["BTC/USDT"], active=False)
    assert entry(r).code == "MARKET_INACTIVE"
    r["BTC/USDT"] = replace(rules["BTC/USDT"], opo_allowed=False, oco_allowed=False)
    assert entry(r).code == "NO_PROTECTION"


# ---------- preço, stop, alvo, taxa ----------

@pytest.mark.parametrize("kw,code", [
    ({"stop": 66000}, "STOP_ABOVE_ENTRY"),
    ({"target": 64000}, "TARGET_BELOW_ENTRY"),
    ({"stop": 64900}, "STOP_TOO_TIGHT"),
    ({"stop": 58000, "target": 90000, "atr": 5000}, "STOP_TOO_WIDE"),        # ~10,9% > 8% (major)
    ({"atr": None}, "NO_ATR"),
    ({"atr": 500}, "STOP_TOO_WIDE_ATR"),                                    # 2665 / 500 = 5,3 ATR
    ({"target": 67000}, "RR_TOO_LOW"),
    ({"target": 65000 * 10}, "TARGET_OUT_OF_BAND"),
    ({"ask": 0}, "BAD_PRICE"),
])
def test_price_rules(rules, kw, code):
    assert entry(rules, **kw).code == code


def test_fees_eat_target(rules):
    # stop 0,6%, alvo 0,8%: R:R passaria com min_rr=1, mas 0,8% < 3 x 0,3% de custo
    c = cfg(min_rr=1, stop_min_pct=0.1)
    r = entry(rules, c=c, stop=64680, target=65580, atr=1000)
    assert r.code == "FEES_EAT_TARGET"


def test_price_sanity(rules):
    c = cfg(slippage_pct={"major": 2, "alt": 2, "meme": 2})
    assert entry(rules, c=c, target=75000).code == "PRICE_SANITY"


def test_meme_stop_limit_is_wider(rules):
    # 14% de stop: permitido para meme (15%), proibido para major (8%)
    assert entry(rules, sym="PEPE/USDT", stop="0.00000860", target="0.00001400", atr="0.000001").ok


# ---------- ajustes de posição ----------

def test_move_stop_only_up(rules):
    r = rules["BTC/USDT"]
    assert check_move_stop(r, 62000, 61000, 65000).code == "STOP_ONLY_UP"
    assert check_move_stop(r, 62000, 62000, 65000).code == "STOP_ONLY_UP"
    assert check_move_stop(r, 62000, 65000, 65000).code == "STOP_ABOVE_PRICE"
    assert check_move_stop(r, 62000, "63000.019", 65000) == Dec("63000.01")


def test_new_target(rules):
    r = rules["BTC/USDT"]
    assert check_new_target(r, 62000, 64000, 65000).code == "TARGET_BELOW_PRICE"
    assert check_new_target(r, 62000, 70000, 65000) == Dec(70000)


def test_partial(rules):
    c = cfg()
    btc = rules["BTC/USDT"]
    assert check_partial(c, btc, Dec("0.0005"), Dec("0.5"), 65000) == Dec("0.00025")
    assert check_partial(c, btc, Dec("0.0005"), Dec("0.95"), 65000).code == "BAD_FRACTION"
    assert check_partial(c, btc, Dec("0.00012"), Dec("0.5"), 65000).code == "PARTIAL_BELOW_MIN"   # ~7,8 USDT total
    pepe = rules["PEPE/USDT"]
    assert check_partial(c, pepe, Dec(500000), Dec("0.5"), "0.00001") == Dec(250000)              # 2,5 USDT cada lado


def test_day_start_sao_paulo():
    # 02:00 UTC = 23:00 do dia anterior em São Paulo
    ds = day_start(datetime(2026, 9, 27, 2, 0, tzinfo=timezone.utc), "America/Sao_Paulo")
    assert (ds.year, ds.month, ds.day, ds.hour) == (2026, 9, 26, 0)
