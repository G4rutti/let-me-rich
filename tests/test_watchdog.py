from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from test_trading_b3 import b3cfg, enter, env  # noqa: F401 (fixture)
from trader import watchdog
from trader.b3 import runtime
from trader.db import get_state, set_state
from trader.kill import kill_b3
from trader.telegram_daemon import handle

TZ = ZoneInfo("America/Sao_Paulo")


def run(env, **kw):
    tasks = []
    r = watchdog.run_once(env, disable_tasks=lambda names: tasks.extend(names) or [f"{n}: desligado" for n in names])
    return r, tasks


def test_tudo_ok_nao_faz_nada(env):
    enter(env)
    r, _ = run(env)
    assert r["action"] is None and env.fake.pos


def test_posicao_sem_sl_zera_e_pausa(env):
    t = enter(env)
    env.fake.pos[t["position_ticket"]].sl = 0.0
    r, _ = run(env)
    assert r["action"] == "pause" and "sem SL" in r["problems"][0]
    assert not env.fake.pos and get_state(env.conn, "b3_paused") is True


def test_volume_maior_que_1(env):
    t = enter(env)
    env.fake.pos[t["position_ticket"]].volume = 2.0
    r, _ = run(env)
    assert r["action"] == "pause" and any("2.0 contratos" in p for p in r["problems"])


def test_posicao_fora_da_janela(env):
    enter(env)
    env.now = lambda: datetime(2026, 10, 1, 17, 35, tzinfo=TZ)
    r, _ = run(env)
    assert r["action"] == "pause" and "fora da janela" in r["problems"][0] and not env.fake.pos


def test_divergencia_posicao_desconhecida(env):
    env.fake.open_foreign()
    r, _ = run(env)
    assert r["action"] == "pause" and any("não conhece" in p for p in r["problems"]) and not env.fake.pos


def test_terminal_desconectado(env):
    enter(env)
    env.fake.term.connected = False
    r, _ = run(env)
    assert r["action"] == "pause" and "desconectado" in r["problems"][0]
    assert get_state(env.conn, "b3_paused") is True


def test_conta_trocada(env):
    env.fake.acc.login = 999
    r, _ = run(env)
    assert r["action"] == "pause" and "conta" in r["problems"][0]


def test_perda_diaria_zera_e_trava_o_dia(env):
    enter(env)
    env.fake.bid, env.fake.ask = 129850, 129855      # aberto: -150 pts = -31 (acima dos 30)
    r, tasks = run(env)
    assert r["action"] == "day" and not env.fake.pos and not tasks
    assert get_state(env.conn, "b3_halted_day") == env.today
    assert run(env)[0]["action"] is None                # já travado: não repete aviso


def test_perda_total_zera_pausa_e_desliga_agendador(env):
    set_state(env.conn, "b3_capital_start_live", {"ts": "2000-01-01T00:00:00+00:00", "brl": 100})
    env.conn.execute("INSERT INTO b3_trades (variant, mode, day, symbol, setup, setup_id, side, status, contracts, "
                     "signal_price, initial_sl, sl, tp, risk_brl, created_at, pnl_brl) VALUES ('real','live',"
                     "'2026-09-30','WINV26','x','s1','long','closed',1,1,1,1,1,23,'2026-09-30T13:00:00+00:00',-60)")
    r, tasks = run(env)
    assert r["action"] == "total" and set(tasks) == set(watchdog.B3_TASKS)
    assert get_state(env.conn, "b3_halted_total") is True and get_state(env.conn, "b3_paused") is True
    assert run(env)[0]["action"] is None                # não desliga de novo a cada minuto


def test_kill_b3(env):
    enter(env)
    off = []
    log = kill_b3(env, disable_task=lambda names: off.extend(names) or ["ok"])
    assert not env.fake.pos and get_state(env.conn, "b3_paused") is True and off == list(watchdog.B3_TASKS)
    assert any("KILL B3" in m for m in env.msgs)


def test_telegram_pause_resume_b3(env):
    handle(env, "/pause")
    assert get_state(env.conn, "b3_paused") is True
    set_state(env.conn, "b3_halted_total", True)
    assert "religar" in handle(env, "/resume")
    assert get_state(env.conn, "b3_paused") is False


def test_preflight(env):
    now = datetime(2026, 10, 1, 8, 0, tzinfo=TZ)
    p = runtime.preflight(env.cfg, env.conn, env.broker, now)
    assert p["status"] == "OK" and p["contract"]["symbol"] == "WINV26", p
    env.fake.acc.trade_mode = env.fake.ACCOUNT_TRADE_MODE_DEMO
    p = runtime.preflight(env.cfg, env.conn, env.broker, now)
    assert p["status"] == "ABORT" and "não é real" in p["problems"][0]
    env.fake.acc.trade_mode = env.fake.ACCOUNT_TRADE_MODE_REAL
    env.fake.info.trade_tick_value = 2.0
    assert runtime.preflight(env.cfg, env.conn, env.broker, now)["status"] == "ABORT"
    env.fake.info.trade_tick_value = 1.0
    env.fake.symbol = "WINZ26"                      # no vencimento do V26 já se opera o Z26
    p = runtime.preflight(env.cfg, env.conn, env.broker, datetime(2026, 10, 14, 8, 0, tzinfo=TZ))
    assert p["status"] == "MANAGE_ONLY" and "vencimento" in p["entries_blocked"][0]
    env.fake.symbol = "WINV26"
    set_state(env.conn, "b3_paused", True)
    assert runtime.preflight(env.cfg, env.conn, env.broker, now)["status"] == "MANAGE_ONLY"
    env.fake.alive = False
    assert runtime.preflight(env.cfg, env.conn, env.broker, now)["status"] == "ABORT"


def test_preflight_mode_off(env):
    env.cfg["mode"] = "off"
    assert runtime.preflight(env.cfg, env.conn, env.broker)["status"] == "ABORT"


def test_make_ctx_dry_usa_papel(env):
    env.cfg["mode"] = "dry"
    assert runtime.make_ctx(env.cfg, env.conn, env.broker, "WINV26").broker.is_paper
    env.cfg["mode"] = "live"
    assert not runtime.make_ctx(env.cfg, env.conn, env.broker, "WINV26").broker.is_paper
    assert runtime.make_ctx(env.cfg, env.conn, env.broker, "WINV26", variant="sombra_regra").broker.is_paper


@pytest.mark.parametrize("argv", [["--religar"]])
def test_religar_exige_yes(argv):
    with pytest.raises(SystemExit):
        watchdog.main(argv)


def test_tarefas_do_agendador_batem_com_o_kill():
    import re
    from pathlib import Path
    ps1 = (Path(__file__).parents[1] / "scripts" / "install_tasks_b3.ps1").read_text(encoding="utf-8")
    assert set(re.findall(r'New-B3Task "([^"]+)"', ps1)) == set(watchdog.B3_TASKS)
