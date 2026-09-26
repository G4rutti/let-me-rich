from datetime import datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest
import yaml

from fake_exchange import FakeExchange
from trader.config import CONFIG_DIR, Config, _freeze
from trader.db import connect, get_state
from trader.sync import preflight, sync
from trader.trading import Ctx, TradeError, move_stop, place_entry, trade


def make_cfg(mode="live", **over):
    r = yaml.safe_load((CONFIG_DIR / "risk.yaml").read_text(encoding="utf-8"))
    u = yaml.safe_load((CONFIG_DIR / "universe.yaml").read_text(encoding="utf-8"))
    r.update(mode=mode, **over)
    return Config(_freeze(r), _freeze(u))


@pytest.fixture
def env(rules):
    ex = FakeExchange(rules, {"BTC/USDT": 65000, "PEPE/USDT": "0.00001", "SOL/USDT": 150, "USDT/BRL": 5.4},
                      {"USDT": 90, "BNB": "0.01"})
    msgs = []
    ctx = Ctx(connect(":memory:"), ex, make_cfg(), cycle_id="c1", notify=msgs.append, sleep=lambda s: None)
    ctx.msgs = msgs
    return ctx


def enter_btc(ctx):
    return place_entry(ctx, symbol="BTC/USDT", horizon="swing", setup="swing_breakout_4h",
                       stop=62400, target=70200, reason="teste", regime="BULL")


def fill_entry(ctx, qty="0.00046", fee_base="0.00000046"):
    t = ctx.conn.execute("SELECT * FROM trades ORDER BY id DESC").fetchone()
    lid = t["entry_list_id"]
    ctx.ex.fill(lid + "-w", qty, 65065, {"BTC": fee_base})
    held = Dec(qty) - Dec(fee_base)
    ctx.ex.orders[lid + "-t"]["info"]["status"] = "NEW"
    ctx.ex.orders[lid + "-s"]["info"]["status"] = "NEW"
    ctx.ex.bal["USDT"]["free"] -= Dec(qty) * 65065
    ctx.ex.bal["BTC"] = {"free": Dec(0), "locked": held}
    return lid, held


def test_dry_mode_sends_nothing(env):
    env.cfg = make_cfg("dry")
    r = enter_btc(env)
    assert r["dry_run"] and env.ex.calls == []
    assert env.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_entry_uses_opoco_and_becomes_open_on_fill(env):
    r = enter_btc(env)
    assert env.ex.calls[0][0] == "opoco"
    assert r["status"] == "pending"
    lid, held = fill_entry(env)
    sync(env)
    t = trade(env.conn, r["trade_id"])
    assert t["status"] == "open" and Dec(str(t["qty"])) == held       # quantidade líquida da taxa em BTC
    assert t["protect_list_id"] == lid
    audit = [x["decision"] for x in env.conn.execute("SELECT decision FROM risk_audit")]
    assert audit[:3] == ["approved", "intent", "result"]            # intent antes da ordem


def test_retry_same_cycle_does_not_duplicate(env):
    enter_btc(env)
    r2 = enter_btc(env)
    assert "já enviada" in r2["status"]
    assert sum(c[0] == "opoco" for c in env.ex.calls) == 1


def test_stop_filled_between_cycles_records_exit(env):
    r = enter_btc(env)
    lid, held = fill_entry(env)
    sync(env)
    env.ex.fill(lid + "-s", held, 62400, {"USDT": "0.03"})
    env.ex.orders[lid + "-t"]["info"]["status"] = "EXPIRED"
    sync(env)
    t = trade(env.conn, r["trade_id"])
    assert t["status"] == "closed" and t["exit_reason"] == "stop"
    assert t["pnl_usd"] < 0 and -1.2 < t["r_multiple"] < -0.8


def test_target_filled_records_win(env):
    r = enter_btc(env)
    lid, held = fill_entry(env)
    sync(env)
    env.ex.fill(lid + "-t", held, 70200)
    env.ex.orders[lid + "-s"]["info"]["status"] = "EXPIRED"
    sync(env)
    t = trade(env.conn, r["trade_id"])
    assert t["exit_reason"] == "target" and t["r_multiple"] > 1.5


def test_position_without_stop_gets_stop_recreated(env):
    r = enter_btc(env)
    lid, held = fill_entry(env)
    sync(env)
    env.ex.cancel_list("BTC/USDT", lid)          # alguém cancelou o OCO na mão
    sync(env)
    oco = [c for c in env.ex.calls if c[0] == "oco"]
    assert len(oco) == 1 and oco[0][2] == env.ex.rules("BTC/USDT").floor_qty(held) and oco[0][3] == Dec("62400")
    t = trade(env.conn, r["trade_id"])
    assert t["status"] == "open" and t["protect_list_id"] == oco[0][5]
    assert any("stop recriado" in m for m in env.msgs)


def test_unprotected_below_stop_sells_at_market(env):
    r = enter_btc(env)
    lid, held = fill_entry(env)
    sync(env)
    env.ex.cancel_list("BTC/USDT", lid)
    env.ex.prices["BTC/USDT"] = Dec(62000)
    sync(env)
    assert any(c[0] == "market_sell" for c in env.ex.calls)
    t = trade(env.conn, r["trade_id"])
    assert t["status"] == "closed" and t["exit_reason"] == "emergency"


def test_oco_failing_twice_triggers_emergency_exit(env):
    r = enter_btc(env)
    lid, held = fill_entry(env)
    sync(env)
    env.ex.cancel_list("BTC/USDT", lid)
    env.ex.fail_oco = 2
    sync(env)
    t = trade(env.conn, r["trade_id"])
    assert t["status"] == "closed" and t["exit_reason"] == "emergency"


def test_pending_entry_times_out_and_is_cancelled(env):
    r = enter_btc(env)
    env.now = lambda: datetime.now(timezone.utc) + timedelta(minutes=30)
    sync(env)
    assert ("cancel_list", "BTC/USDT", trade(env.conn, r["trade_id"])["entry_list_id"]) in env.ex.calls
    assert trade(env.conn, r["trade_id"])["status"] == "cancelled"


def test_orphan_balance_gets_protected(env):
    env.ex.bal["SOL"] = {"free": Dec("0.2"), "locked": Dec(0)}   # 30 USDT comprados na mão
    sync(env)
    oco = [c for c in env.ex.calls if c[0] == "oco"]
    assert len(oco) == 1 and oco[0][1] == "SOL/USDT" and oco[0][3] < 150
    t = env.conn.execute("SELECT * FROM trades WHERE symbol='SOL/USDT'").fetchone()
    assert t["setup"] == "orphan" and t["status"] == "open"


def test_move_stop_only_up_and_recreates_oco(env):
    enter_btc(env)
    fill_entry(env)
    sync(env)
    with pytest.raises(TradeError) as e:
        move_stop(env, "BTC/USDT", 60000)
    assert e.value.code == "STOP_ONLY_UP"
    move_stop(env, "BTC/USDT", 64000)
    assert env.ex.calls[-1][0] == "oco" and env.ex.calls[-1][3] == Dec("64000")


def test_circuit_breaker_pauses_after_failures(env):
    enter_btc(env)
    fill_entry(env)
    sync(env)
    lid = env.conn.execute("SELECT protect_list_id FROM trades").fetchone()[0]
    env.ex.cancel_list("BTC/USDT", lid)
    env.ex.fail_oco = 10
    env.ex.prices["BTC/USDT"] = Dec(65000)
    env.ex.market_sell = lambda *a: (_ for _ in ()).throw(__import__("trader.exchange").exchange.ExchangeError("X", "down"))
    sync(env)
    assert get_state(env.conn, "consecutive_order_failures") >= 3
    assert get_state(env.conn, "paused") is True


def test_preflight_ok_and_abort(env):
    assert preflight(env)["status"] == "OK"
    env.ex.api_restrictions = lambda: {"enableSpotAndMarginTrading": True, "enableWithdrawals": True, "ipRestrict": True}
    p = preflight(env)
    assert p["status"] == "ABORT" and "SAQUE" in p["problems"][0]


def test_take_partial_sells_fraction_and_reprotects_rest(env):
    from trader.trading import take_partial
    env.ex.bal["USDT"]["free"] = Dec(300)
    env.cfg = make_cfg(max_order_usd=100, max_position_pct=100, risk_pct={"major": 3, "alt": 1, "meme": 0.5})
    enter_btc(env)
    lid, held = fill_entry(env, qty="0.0012", fee_base="0.0000012")
    sync(env)
    r = take_partial(env, "BTC/USDT", 0.5, "realiza metade")
    kinds = [c[0] for c in env.ex.calls]
    assert kinds[-3:] == ["cancel_list", "market_sell", "oco"]
    assert Dec(r["sold"]) == Dec("0.00059")
    t = env.conn.execute("SELECT * FROM trades").fetchone()
    assert t["status"] == "open" and t["proceeds_usd"] > 0
