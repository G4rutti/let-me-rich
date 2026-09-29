from datetime import date, datetime, timedelta
from decimal import Decimal as Dec

import pytest

from b3_data import TZ, daily, day, ramp
from fake_mt5 import FakeMT5
from trader.b3 import features as ft
from trader.b3 import flow
from trader.b3.regime import regime, trend
from trader.broker.base import Tick
from trader.broker.mt5 import MT5Broker
from trader.collectors.recorder import load_bars, record
from trader.db import connect

D1 = date(2026, 10, 1)


def test_vwap_volume_igual_e_media_do_preco_tipico():
    bars = day(D1, [100, 110, 120], wick=0)
    vb = ft.vwap_bands(bars)
    tp = [(max(o, c) + min(o, c) + c) / 3 for o, c in ((100, 100), (100, 110), (110, 120))]
    assert vb["vwap"] == pytest.approx(sum(tp) / 3)
    assert vb["vwap_up1"] > vb["vwap"] > vb["vwap_dn1"] and vb["vwap_up2"] > vb["vwap_up1"]
    assert ft.vwap_bands([]) is None


def test_opening_range_so_depois_da_janela():
    bars = day(D1, ramp(130000, 130300, 20), wick=0)
    assert ft.opening_range(bars[:14], 15) is None
    hi, lo = ft.opening_range(bars, 15)
    assert (hi, lo) == (max(float(b.high) for b in bars[:15]), 130000)
    assert ft.opening_range(bars, 30) is None


def test_niveis_dia_anterior_e_gap():
    d = daily(D1, 60)
    bars = day(D1, ramp(126500, 126700, 100))
    lv = ft.levels(bars, d, D1)
    prev = [b for b in d if b.time.date() < D1][-1]
    assert lv["pdh"] == float(prev.high) and lv["pdc"] == float(prev.close)
    assert {"vwap", "or15_high", "or30_low", "day_open", "day_high"} <= set(lv) <= set(ft.LEVEL_REFS)
    s = ft.snapshot(bars, d, bars[-1].time + timedelta(minutes=1))
    assert s["gap"]["points"] == 126500 - float(prev.close) and s["atr_5m"] and s["atr_daily"]
    assert s["distance"]["day_open"]["ticks"] == (126500 - s["last"]) / 5


def test_volume_relativo():
    prev = day(date(2026, 9, 30), [100] * 30, vol=100)
    today = day(D1, [100] * 30, vol=200)
    now = today[20].time
    assert ft.relative_volume(prev + today, now) == pytest.approx(2.0)
    assert ft.relative_volume(today, now) is None


def test_regime():
    up = daily(D1, 80, step=100)
    down = daily(D1, 80, step=-100)
    assert trend(up) == "alta" and trend(down) == "baixa" and trend(up[:30]) is None
    r = regime(up, up)
    assert r["daily"] == "alta" and r["vol"] == "normal"


def tk(sec, vol, side):
    return Tick(datetime(2026, 10, 1, 10, 0, sec, tzinfo=TZ), Dec(1), Dec(1), Dec(1), Dec(vol), side)


def test_agressao():
    ticks = [tk(1, 3, "long"), tk(2, 1, "short"), tk(3, 2, "long"), tk(4, 5, None)]
    a = flow.aggression(ticks)
    assert a["buy"] == 5 and a["sell"] == 1 and a["delta"] == 4 and a["coverage"] == 0.75
    assert flow.aggression([tk(1, 3, None)]) == {"status": "indisponível"}
    w = flow.aggression_windows(ticks, datetime(2026, 10, 1, 10, 1, tzinfo=TZ))
    assert w["5m"]["delta"] == 4 and w["day"]["buy"] == 5


def test_book():
    b = {"bids": [(Dec(1), Dec(30)), (Dec(0), Dec(10))], "asks": [(Dec(2), Dec(10))]}
    assert flow.book_imbalance(b)["imbalance"] == 0.6
    assert flow.book_imbalance(None)["status"] == "indisponível"


def test_recorder_grava_barras_e_ticks():
    fake = FakeMT5()
    base = datetime(2026, 10, 1, 10, 0).timestamp()
    fake.rates = [{"time": base + 60 * i, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 7,
                   "real_volume": 10} for i in range(5)]
    fake.ticks = [{"time_msc": int(fake.now * 1000) + i, "bid": 1.0, "ask": 2.0, "last": 1.5, "volume": 1,
                   "volume_real": 1.0, "flags": fake.TICK_FLAG_BUY} for i in range(3)]
    conn = connect(":memory:")
    b = MT5Broker(fake, magic=1)
    now = datetime(2026, 10, 1, 10, 5, tzinfo=TZ)
    r = record(conn, b, "WINV26", now)
    assert r == {"bars": 4, "ticks": 3, "book": False}
    assert record(conn, b, "WINV26", now)["ticks"] == 0          # não duplica
    bars = load_bars(conn, "WINV26")
    assert len(bars) == 4 and bars[0].volume == 10
    assert conn.execute("SELECT aggressor FROM b3_ticks").fetchone()["aggressor"] == "long"
