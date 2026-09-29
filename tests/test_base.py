from decimal import Decimal

import pytest

from trader import indicators as ind
from trader.config import ConfigError, load_config, validate_risk
from trader.broker.binance_spot import client_id, rules_from_info


def test_config_loads_and_categorizes():
    cfg = load_config()
    assert cfg.risk["mode"] in ("off", "dry", "live")
    assert cfg.category("BTC/USDT") == "major"
    assert cfg.category("PEPE/USDT") == "meme"
    assert cfg.category("FET/USDT") == "alt"
    with pytest.raises(TypeError):
        cfg.risk["mode"] = "live"  # congelado


def test_live_requires_order_cap():
    r = dict(load_config().risk)
    r = {k: (dict(v) if hasattr(v, "keys") else v) for k, v in r.items()}
    r["mode"] = "live"
    r["max_order_usd"] = None
    with pytest.raises(ConfigError):
        validate_risk(r)


def test_rules_from_real_fixtures(rules):
    btc, pepe = rules["BTC/USDT"], rules["PEPE/USDT"]
    assert btc.min_notional == Decimal("5") and pepe.min_notional == Decimal("1")
    assert btc.opo_allowed and btc.oco_allowed
    assert btc.floor_qty("0.123456789") == Decimal("0.12345")
    assert pepe.floor_qty("123456.9") == Decimal("123456")
    assert btc.floor_price("65000.019") == Decimal("65000.01")
    assert btc.ceil_price("65000.011") == Decimal("65000.02")


def test_client_id_deterministic_and_valid():
    import re
    a, b = client_id("c1", "BTC/USDT", "entry"), client_id("c1", "BTC/USDT", "entry")
    assert a == b and a != client_id("c2", "BTC/USDT", "entry")
    assert re.fullmatch(r"[.A-Z:/a-z0-9_-]{1,36}", a + "-w")


def test_indicators():
    closes = [float(i) for i in range(1, 60)]
    assert ind.ema(closes, 20)[-1] == pytest.approx(49.5, rel=1e-3)  # série linear: EMA atrasa (n-1)/2
    assert ind.rsi(closes) == 100.0
    candles = [[0, c, c + 1, c - 1, c, 1] for c in closes]
    assert ind.atr(candles) == pytest.approx(2.0, rel=0.01)
    assert ind.donchian_high(candles, 20) == closes[-2] + 1
