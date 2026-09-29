from datetime import datetime
from decimal import Decimal as Dec
from zoneinfo import ZoneInfo

import pytest

from fake_mt5 import FakeMT5
from trader import risk_b3 as rk
from trader import trading_b3 as tb
from trader.b3.config import load_b3
from trader.broker.base import BrokerError
from trader.broker.mt5 import MT5Broker
from trader.broker.sim import SimBroker
from trader.db import connect, get_state

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=TZ)


def b3cfg(mode="live", **ex):
    c = load_b3()
    d = {k: (dict(v) if hasattr(v, "keys") else v) for k, v in c.items()}
    d.update(mode=mode, account_number=42)
    d["executor"].update(ex)
    return d


@pytest.fixture
def env():
    fake = FakeMT5()
    broker = MT5Broker(fake, magic=770101, sleep=lambda s: None, fill_wait_s=0.2)
    msgs = []
    ctx = tb.B3Ctx(connect(":memory:"), broker, b3cfg(), "WINV26", notify=msgs.append, now=lambda: NOW,
                   sleep=lambda s: None)
    ctx.fake, ctx.msgs = fake, msgs
    return ctx


def approve(ctx, side="long"):
    base = dict(setup_id="s1", max_entries=1, bid=ctx.fake.bid, ask=ctx.fake.ask, atr5m=100, now=NOW)
    if side == "long":
        kw = dict(side="long", stop=ctx.fake.ask - 100, target=ctx.fake.ask + 200)
    else:
        kw = dict(side="short", stop=ctx.fake.bid + 100, target=ctx.fake.bid - 200)
    a = rk.check_entry(ctx.cfg, rk.DayState(risk_level="normal"), **base, **kw)
    assert a.ok, a
    return a


def enter(ctx, side="long"):
    return tb.enter(ctx, approve(ctx, side), setup="opening_range_breakout", setup_id="s1",
                    plan={"version": 1, "bias": side, "risk_level": "normal"})


@pytest.mark.parametrize("side", ["long", "short"])
def test_entrada_vai_com_sl_e_tp_no_mesmo_envio(env, side):
    t = enter(env, side)
    req = env.fake.sent[0]
    assert req["sl"] and req["tp"] and req["volume"] == 1.0 and req["magic"] == 770101
    assert req["type"] == (env.fake.ORDER_TYPE_BUY if side == "long" else env.fake.ORDER_TYPE_SELL)
    assert t["status"] == "open" and t["mode"] == "live" and t["position_ticket"]
    assert len(env.fake.sent) == 1                                    # SL confirmado: nada mais enviado
    assert any("ENTRADA" in m for m in env.msgs)


def test_sl_ignorado_e_reposto(env):
    env.fake.drop_sl = True
    t = enter(env)
    assert env.fake.sent[1]["action"] == env.fake.TRADE_ACTION_SLTP
    assert t["status"] == "open"
    assert env.fake.pos[t["position_ticket"]].sl == t["sl"]


def test_sem_sl_confirmado_zera_a_mercado(env):
    env.cfg["executor"]["sl_confirm_seconds"] = 0
    env.fake.drop_sl = env.fake.ignore_sltp = True
    t = enter(env)
    assert t["status"] == "closed" and t["exit_reason"] == "sem_sl"
    assert not env.fake.pos


def test_execucao_placed_espera_a_posicao(env):
    env.fake.hide_fills = 3
    assert enter(env)["status"] == "open"


@pytest.mark.parametrize("mode,real,login", [("dry", True, 42), ("live", False, 42), ("live", True, 7)])
def test_live_bloqueado_sem_conta_real_certa(env, mode, real, login):
    env.cfg["mode"] = mode
    env.fake.acc.trade_mode = env.fake.ACCOUNT_TRADE_MODE_REAL if real else env.fake.ACCOUNT_TRADE_MODE_DEMO
    env.fake.acc.login = login
    with pytest.raises(tb.TradeError) as e:
        enter(env)
    assert e.value.code == "NOT_LIVE" and not env.fake.sent


def test_rejeicao_conta_falha_e_circuit_breaker(env):
    for i in range(3):
        env.fake.reject = env.fake.TRADE_RETCODE_REJECT
        with pytest.raises(tb.TradeError, match="ORDER_FAILED"):
            enter(env)
    assert get_state(env.conn, "b3_paused") is True
    assert any("CIRCUIT" in m for m in env.msgs)
    assert tb.day_state(env).paused


@pytest.mark.parametrize("side,px,reason,pnl", [("long", 129895, "stop", -22.0), ("long", 130210, "target", 40.0),
                                                ("short", 130105, "stop", -22.0), ("short", 129790, "target", 40.0)])
def test_reconcile_contabiliza_saida_na_corretora(env, side, px, reason, pnl):
    t = enter(env, side)
    env.fake.hit(*((px, px + 5) if side == "long" else (px - 5, px)))
    r = tb.reconcile(env)
    t = tb.trade(env.conn, t["id"])
    assert t["status"] == "closed" and t["exit_reason"] == reason and not r["divergences"]
    assert t["pnl_brl"] == pytest.approx(pnl, abs=1.1)


def test_estado_do_dia_apos_stop(env):
    enter(env)
    env.fake.hit(129890)
    tb.reconcile(env)
    st = tb.day_state(env, {"risk_level": "normal", "bias": "long"})
    assert st.trades_today == 1 and st.entries_by_setup == {"s1": 1}
    assert st.realized_today_brl < -20 and st.last_stop_at is not None and not st.open_position


def test_perda_aberta_entra_no_estado(env):
    enter(env)
    env.fake.bid, env.fake.ask = 129950, 129955
    st = tb.day_state(env, {"risk_level": "normal"})
    assert st.open_position and st.open_pnl_brl == Dec("-12.0")        # -55 pts x 0,2 - 1


def test_posicao_desconhecida_e_ordem_pendente_sao_divergencia(env):
    env.fake.open_foreign()
    env.fake.ords[1] = type("O", (), dict(ticket=1, symbol="WINV26", type=2, volume_current=1.0, price_open=1.0,
                                           sl=0.0, tp=0.0, magic=0, comment=""))()
    r = tb.reconcile(env)
    assert len(r["divergences"]) == 2


def test_flatten_zera_tudo_inclusive_desconhecida(env):
    t = enter(env)
    env.fake.open_foreign(buy=False)
    log = tb.flatten_all(env, "flatten")
    assert not env.fake.pos and len([x for x in log if "zerado" in x]) == 2
    assert tb.trade(env.conn, t["id"])["exit_reason"] == "flatten"


def test_move_stop_so_a_favor(env):
    t = enter(env)
    env.fake.bid, env.fake.ask = 130100, 130105
    with pytest.raises(tb.TradeError, match="STOP_ONLY_FAVOR"):
        tb.move_stop(env, t, t["sl"] - 50, "teste")
    t = tb.move_stop(env, t, 130005, "breakeven")
    assert t["sl"] == 130005 and env.fake.pos[t["position_ticket"]].sl == 130005


def test_halt_total_pausa(env):
    enter(env)
    tb.halt(env, "total", "perda total")
    assert not env.fake.pos and get_state(env.conn, "b3_halted_total") is True
    st = tb.day_state(env, {"risk_level": "normal"})
    assert st.halted_total and st.paused
    assert rk.loss_action(env.cfg, st) == "total"


def test_halt_dia_so_trava_hoje(env):
    tb.halt(env, "day", "perda diária")
    assert tb.day_state(env).halted_today and not tb.day_state(env).paused


def test_terminal_caiu(env):
    env.fake.alive = False
    assert not env.broker.connected()
    with pytest.raises(BrokerError):
        env.broker.positions()


def test_papel_nunca_envia(env):
    env.cfg["mode"] = "dry"
    env.broker = SimBroker(MT5Broker(env.fake, magic=1))
    t = enter(env)
    assert t["mode"] == "dry" and t["status"] == "open" and not env.fake.sent
    env.fake.bid, env.fake.ask = 129890, 129895
    tb.reconcile(env)
    assert tb.trade(env.conn, t["id"])["exit_reason"] == "stop"


def test_spec_e_conta_do_adaptador(env):
    s = env.broker.symbol_spec("WINV26")
    assert s.tick_size == 5 and s.tick_value == 1 and s.tradeable and s.expiration.day == 14
    a = env.broker.account()
    assert a.is_real and a.number == 42 and a.trade_allowed
