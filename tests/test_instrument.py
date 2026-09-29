import copy
from datetime import date, datetime
from decimal import Decimal as Dec

import pytest
import yaml

from trader.b3 import config as b3c
from trader.b3.instrument import (business_days_until, check_spec, contract, current_contract, expiry_date,
                                  is_expiry_day)
from trader.broker.base import SymbolSpec
from trader.config import CONFIG_DIR, ConfigError


def raw():
    return yaml.safe_load((CONFIG_DIR / "b3.yaml").read_text(encoding="utf-8"))


def write(tmp_path, c):
    (tmp_path / "b3.yaml").write_text(yaml.safe_dump(c), encoding="utf-8")
    return tmp_path


def test_config_do_repo_carrega_e_teto_bate_com_spec():
    c = b3c.load_b3()
    assert c["mode"] == "off"
    assert b3c.cost_brl(c) == pytest.approx(3.0)
    assert b3c.stop_ceiling(c) == 135


def test_mode_off_sem_aspas(tmp_path):
    c = raw()
    c["mode"] = False
    assert b3c.load_b3(write(tmp_path, c))["mode"] == "off"


def test_max_contracts_clampado(tmp_path):
    c = raw()
    c["risk"]["max_contracts_hard"] = 5
    assert b3c.load_b3(write(tmp_path, c))["risk"]["max_contracts_hard"] == 1


@pytest.mark.parametrize("path,value,msg", [
    (("risk", "stop_max_points"), 140, "teto 135"),                   # acima do teto, conta na mensagem
    (("risk", "stop_max_points"), 60, "stop_min"),                    # max <= min
    (("risk", "stop_min_points"), 62, "múltiplo do tick"),
    (("reduced_day", "stop_max_points"), 150, "reduced_day"),
    (("risk", "daily_loss_max_brl"), 20, "risk_per_trade <= daily_loss_max"),
    (("risk", "total_loss_max_brl"), 200, "total_loss_max <= capital_start"),
    (("session", "flatten_at"), "16:00", "flatten_at"),
    (("session", "no_entry_before"), "9:15", "HH:MM"),
    (("risk", "min_rr"), "2", "min_rr"),
    (("mode",), "yolo", "mode"),
])
def test_config_inconsistente_recusa(tmp_path, path, value, msg):
    c = raw()
    d = c
    for k in path[:-1]:
        d = d[k]
    d[path[-1]] = value
    with pytest.raises(ConfigError, match=msg):
        b3c.load_b3(write(tmp_path, c))


def test_live_exige_conta(tmp_path):
    c = raw()
    c["mode"] = "live"
    with pytest.raises(ConfigError, match="account_number"):
        b3c.load_b3(write(tmp_path, c))
    c["account_number"] = 123
    assert b3c.load_b3(write(tmp_path, copy.deepcopy(c)))["mode"] == "live"


def test_vencimento_quarta_mais_proxima_do_15():
    assert expiry_date(2026, 10) == date(2026, 10, 14)   # 15 é quinta
    assert expiry_date(2026, 12) == date(2026, 12, 16)   # 15 é terça
    assert expiry_date(2026, 8) == date(2026, 8, 12)     # 15 é sábado -> quarta 12
    assert expiry_date(2026, 11, ).weekday() == 2
    assert contract("WIN", 2026, 10).symbol == "WINV26"


def test_contrato_vigente_e_rolagem():
    assert current_contract("WIN", date(2026, 9, 29), 2).symbol == "WINV26"
    assert current_contract("WIN", date(2026, 10, 9), 2).symbol == "WINV26"   # sex: faltam 3 úteis
    assert current_contract("WIN", date(2026, 10, 12), 2).symbol == "WINZ26"  # seg: faltam 2 -> rola
    assert current_contract("WIN", date(2026, 10, 14), 0).symbol == "WINZ26"  # dia do vencimento
    assert current_contract("WIN", date(2026, 12, 20), 2).symbol == "WING27"
    assert business_days_until(date(2026, 10, 9), date(2026, 10, 14)) == 3


def test_dia_de_vencimento():
    assert is_expiry_day("WIN", date(2026, 10, 14))
    assert not is_expiry_day("WIN", date(2026, 10, 13))
    assert is_expiry_day("WIN", date(2026, 10, 15), broker_expiry=date(2026, 10, 15))   # feriado adiou


def spec(**kw):
    base = dict(symbol="WINV26", tick_size=Dec(5), tick_value=Dec(1), volume_min=Dec(1), volume_step=Dec(1),
                tradeable=True, expiration=datetime(2026, 10, 14, 18))
    return SymbolSpec(**{**base, **kw})


def test_check_spec():
    cfg = b3c.load_b3()
    c = contract("WIN", 2026, 10)
    assert check_spec(cfg, spec(), c) == ([], [])
    assert "valor do ponto" in check_spec(cfg, spec(tick_value=Dec(2)), c)[0][0]
    assert "tick do MT5" in check_spec(cfg, spec(tick_size=Dec(1)), c)[0][0]
    assert check_spec(cfg, spec(tradeable=False), c)[0]
    assert check_spec(cfg, spec(volume_step=Dec("0.5")), c)[0]
    assert check_spec(cfg, spec(expiration=datetime(2026, 10, 15)), c)[1]
