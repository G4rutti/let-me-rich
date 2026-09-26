from datetime import datetime, timezone
from decimal import Decimal as Dec

from fake_exchange import FakeExchange
from test_sync import make_cfg
from trader import shadow
from trader.db import connect
from trader.regime import classify
from trader.scan import features, score


def candles(n, start, step, vol=100.0, last_vol=None):
    out = []
    for i in range(n):
        p = start + step * i
        out.append([i * 3_600_000, p, p * 1.005, p * 0.995, p, vol])
    if last_vol:
        out[-1][5] = last_vol
    return out


def test_regime_classify():
    up, down = candles(120, 100, 1), candles(120, 300, -1)
    assert classify(up, up)["regime"] == "BULL"
    assert classify(down, down)["regime"] == "BEAR"
    assert classify(up, down)["regime"] == "NEUTRO"
    assert classify(up[:10], up[:10])["regime"] == "BEAR"   # sem dado = conservador


def test_features_and_score_prefer_breakout_with_volume():
    c4 = candles(200, 50, 0.5)
    c4[-1][4] = c4[-1][2] = c4[-2][2] * 1.03                     # fecha 3% acima da máxima anterior
    f_up = features(candles(120, 100, 0.5, last_vol=600), c4)
    f_flat = features(candles(120, 100, 0), candles(200, 100, 0))
    assert f_up["breakout_4h"] and f_up["vol_spike_1h"] == 6.0
    w = make_cfg().universe["scan"]["weights"]
    assert score(f_up, w["meme"]) > score(f_flat, w["meme"])
    assert score(f_up, w["major"]) > score(f_flat, w["major"])


def test_shadow_opens_through_risk_and_closes_on_target(rules):
    ex = FakeExchange(rules, {"BTC/USDT": 65000})
    conn = connect(":memory:")
    cfg = make_cfg("dry")
    c = {"symbol": "BTC/USDT", "category": "major", "price": 65000.0, "breakout_4h": True,
         "ema20_gt_ema50_4h": True, "atr_4h": 1000.0, "atr_1h": 300.0, "vol_spike_1h": 1, "ret_1h": 0, "rsi_1h": 60}
    assert shadow.signal(c)[0] == "swing_breakout_4h"
    r = shadow.step(conn, ex, cfg, [c], "BULL")
    assert r["shadow_opened"] == 1 and ex.calls == []                  # nunca envia ordem
    o = conn.execute("SELECT * FROM shadow_trades").fetchone()
    assert o["target_price"] > 65000 > o["stop_price"]
    ex.prices["BTC/USDT"] = Dec(80000)                                 # velas passam do alvo
    r = shadow.step(conn, ex, cfg, [], "BULL")
    o = conn.execute("SELECT * FROM shadow_trades").fetchone()
    assert r["shadow_closed"] == 1 and o["exit_reason"] == "target" and o["pnl_usd"] > 0


def test_shadow_respects_regime(rules):
    ex = FakeExchange(rules, {"PEPE/USDT": "0.00001"})
    conn = connect(":memory:")
    c = {"symbol": "PEPE/USDT", "category": "meme", "price": 0.00001, "breakout_4h": False,
         "ema20_gt_ema50_4h": False, "atr_4h": 0.000001, "atr_1h": 0.0000004, "vol_spike_1h": 5, "ret_1h": 2, "rsi_1h": 70}
    assert shadow.step(conn, ex, make_cfg("dry"), [c], "BEAR")["shadow_opened"] == 0
    assert shadow.step(conn, ex, make_cfg("dry"), [c], "BULL")["shadow_opened"] == 1
