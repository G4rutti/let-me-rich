"""Carrega e valida config/b3.yaml. Inválida ou inconsistente = ConfigError = não opera."""
import math
import re
from datetime import time
from pathlib import Path
from types import MappingProxyType

import yaml

from trader.config import CONFIG_DIR, ConfigError, _freeze

TZ = "America/Sao_Paulo"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _n(d: dict, key: str, lo: float, hi: float | None = None, integer: bool = False) -> None:
    v = d.get(key)
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= lo and (hi is None or v <= hi)
    if not ok or (integer and v != int(v)):
        raise ConfigError(f"b3.yaml {key}={v!r} inválido (esperado {'inteiro' if integer else 'número'} "
                          f"entre {lo} e {hi})")


def hhmm(s: str) -> time:
    return time(int(s[:2]), int(s[3:]))


def cost_brl(cfg) -> float:
    """Custo estimado de um trade de 1 contrato: taxas ida+volta + slippage."""
    r = cfg["risk"]
    return r["costs_per_contract_brl"] + r["slippage_points"] * cfg["instrument"]["point_value_brl"]


def stop_ceiling(cfg) -> int:
    """Maior stop (pontos, múltiplo do tick) que cabe no risco por trade já descontado o custo."""
    i = cfg["instrument"]
    raw = math.floor(round((cfg["risk"]["risk_per_trade_brl"] - cost_brl(cfg)) / i["point_value_brl"], 6))
    return raw // i["tick_points"] * i["tick_points"]


def validate(c: dict) -> None:
    if c.get("mode") not in ("off", "dry", "live"):
        raise ConfigError("b3.yaml mode deve ser off | dry | live")
    if c["mode"] == "live" and not (isinstance(c.get("account_number"), int) and c["account_number"] > 0):
        raise ConfigError("b3.yaml mode live exige account_number (conta real esperada)")
    _n(c, "capital_start_brl", 1)
    _n(c, "magic", 1, 2**31 - 1, integer=True)
    i, r, rd, s, f, e = (c.get(k) or {} for k in ("instrument", "risk", "reduced_day", "session", "filters", "executor"))
    if not isinstance(i.get("root"), str) or not re.fullmatch(r"[A-Z]{3}", i["root"]):
        raise ConfigError("b3.yaml instrument.root deve ser 3 letras (ex.: WIN)")
    _n(i, "point_value_brl", 0.01)
    _n(i, "tick_points", 1, integer=True)
    _n(i, "roll_days_before_expiry", 0, 10, integer=True)
    _n(r, "max_contracts_hard", 1, integer=True)
    for k in ("risk_per_trade_brl", "daily_loss_max_brl", "total_loss_max_brl"):
        _n(r, k, 1)
    _n(r, "max_trades_per_day", 1, 10, integer=True)
    _n(r, "cooldown_after_stop_min", 0)
    _n(r, "stop_min_points", 1, integer=True)
    _n(r, "stop_max_points", 1, integer=True)
    _n(r, "max_stop_atr", 0.1, 10)
    _n(r, "min_rr", 1, 10)
    _n(r, "costs_per_contract_brl", 0)
    _n(r, "slippage_points", 0, integer=True)
    _n(r, "min_target_cost_multiple", 1)
    _n(r, "max_consecutive_order_failures", 1, integer=True)
    _n(rd, "max_trades_per_day", 1, 10, integer=True)
    _n(rd, "stop_max_points", 1, integer=True)
    if not isinstance(rd.get("only_with_bias"), bool):
        raise ConfigError("b3.yaml reduced_day.only_with_bias deve ser true/false")
    for k in ("plan_deadline", "no_entry_before", "no_entry_after", "flatten_at"):
        if not isinstance(s.get(k), str) or not _HHMM.match(s[k]):
            raise ConfigError(f"b3.yaml session.{k} deve ser HH:MM")
    if not hhmm(s["plan_deadline"]) < hhmm(s["no_entry_before"]) < hhmm(s["no_entry_after"]) < hhmm(s["flatten_at"]):
        raise ConfigError("b3.yaml session: exige plan_deadline < no_entry_before < no_entry_after < flatten_at")
    _n(s, "revise_every_min", 15, 240, integer=True)
    _n(f, "block_event_window_min", 0, 240, integer=True)
    _n(f, "max_spread_ticks", 1, integer=True)
    if not isinstance(f.get("block_expiry_day"), bool):
        raise ConfigError("b3.yaml filters.block_expiry_day deve ser true/false")
    _n(e, "poll_seconds", 0.5, 30)
    _n(e, "sl_confirm_seconds", 1, 30)
    _n(e, "watchdog_every_s", 10, 300)
    _n(e, "book_every_s", 1, 300)

    # ---- regra de consistência (seção 7 do SPEC): nunca "corrige" em silêncio
    tick = i["tick_points"]
    for k, v in (("stop_min_points", r["stop_min_points"]), ("stop_max_points", r["stop_max_points"]),
                 ("reduced_day.stop_max_points", rd["stop_max_points"])):
        if v % tick:
            raise ConfigError(f"b3.yaml {k}={v} não é múltiplo do tick ({tick})")
    ceil = stop_ceiling(c)
    cost = cost_brl(c)
    if not r["stop_min_points"] < r["stop_max_points"] <= ceil:
        raise ConfigError(
            f"b3.yaml stop inconsistente: exige stop_min ({r['stop_min_points']}) < stop_max ({r['stop_max_points']}) "
            f"<= teto {ceil} = floor((risk_per_trade {r['risk_per_trade_brl']} - custo {cost:.2f}) / "
            f"{i['point_value_brl']}) arredondado ao tick {tick}")
    if not r["stop_min_points"] <= rd["stop_max_points"] <= r["stop_max_points"]:
        raise ConfigError("b3.yaml reduced_day.stop_max_points deve ficar entre stop_min_points e stop_max_points")
    if not r["risk_per_trade_brl"] <= r["daily_loss_max_brl"] <= r["total_loss_max_brl"] <= c["capital_start_brl"]:
        raise ConfigError("b3.yaml exige risk_per_trade <= daily_loss_max <= total_loss_max <= capital_start")


def load_b3(config_dir: Path = CONFIG_DIR) -> MappingProxyType:
    c = yaml.safe_load((config_dir / "b3.yaml").read_text(encoding="utf-8"))
    if not isinstance(c, dict):
        raise ConfigError("b3.yaml vazio ou inválido")
    if c.get("mode") is False:            # YAML 1.1: `mode: off` sem aspas vira False
        c["mode"] = "off"
    validate(c)
    c["risk"]["max_contracts_hard"] = 1   # teto duro: qualquer valor acima de 1 é ignorado
    return _freeze(c)
