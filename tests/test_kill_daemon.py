from decimal import Decimal as Dec

from test_sync import enter_btc, env, fill_entry  # noqa: F401 (fixture)
from trader.db import get_state
from trader.kill import kill
from trader.sync import sync
from trader.telegram_daemon import handle


def test_kill_cancels_sells_pauses_and_disables_scheduler(env):
    r = enter_btc(env)
    fill_entry(env)
    sync(env)
    env.ex.bal["SOL"] = {"free": Dec("0.1"), "locked": Dec(0)}       # saldo solto também é vendido
    disabled = []
    log = kill(env, disable_task=lambda: disabled.append(1) or ["agendador desligado"])
    kinds = [c[0] for c in env.ex.calls]
    assert "cancel_all" in kinds
    sold = {c[1] for c in env.ex.calls if c[0] == "market_sell"}
    assert sold == {"BTC/USDT", "SOL/USDT"}
    assert "BNB" in env.ex.bal and env.ex.bal["BNB"]["free"] > 0     # BNB de taxa fica
    t = env.conn.execute("SELECT * FROM trades WHERE id=?", (r["trade_id"],)).fetchone()
    assert t["status"] == "closed" and t["exit_reason"] == "kill"
    assert get_state(env.conn, "paused") is True and disabled
    assert any("KILL" in m for m in env.msgs)


def test_kill_command_needs_confirmation(env):
    assert "confirme" in handle(env, "/kill")
    assert get_state(env.conn, "paused") is None


def test_pause_resume(env):
    handle(env, "/pause")
    assert get_state(env.conn, "paused") is True
    handle(env, "/resume")
    assert get_state(env.conn, "paused") is False
    assert "banca" in handle(env, "/status")


def test_cycle_lock_is_exclusive():
    import pytest
    from trader.lock import exclusive
    with exclusive("test"):
        with pytest.raises(BlockingIOError):
            with exclusive("test"):
                pass
    with exclusive("test"):   # liberado depois
        pass
