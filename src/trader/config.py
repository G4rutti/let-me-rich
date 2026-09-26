"""Carrega e valida config/*.yaml e config/.env. Nenhuma função aqui escreve config."""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CATEGORIES = ("major", "alt", "meme")
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}/USDT$")


class ConfigError(Exception):
    pass


def _freeze(obj):
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def _num(d, key, lo=0.0, hi=None, nullable=False):
    v = d.get(key)
    if v is None and nullable:
        return
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < lo or (hi is not None and v > hi):
        raise ConfigError(f"{key}={v!r} inválido (esperado número entre {lo} e {hi})")


def validate_risk(r: dict) -> None:
    if r.get("mode") not in ("off", "dry", "live"):
        raise ConfigError("mode deve ser off | dry | live")
    if r["mode"] == "live" and not isinstance(r.get("max_order_usd"), (int, float)):
        raise ConfigError("mode live exige max_order_usd numérico")
    for k in ("max_order_usd", "max_daily_notional_usd"):
        _num(r, k, lo=1)
    for k, hi in (("max_position_pct", 100), ("stop_min_pct", 50), ("daily_loss_max_pct", 50),
                  ("fee_pct", 5), ("max_entry_premium_pct", 5)):
        _num(r, k, hi=hi)
    for k in ("max_open_positions", "max_trades_per_day", "cooldown_after_stop_h", "max_stop_atr",
              "min_rr", "min_move_fee_multiple", "max_consecutive_order_failures",
              "min_notional_buffer", "partial_min_notional_buffer", "partial_fill_timeout_min"):
        _num(r, k)
    for k in ("risk_pct", "max_exposure_pct", "stop_max_pct", "slippage_pct", "bear_blocks"):
        if set(r.get(k, {})) != set(CATEGORIES):
            raise ConfigError(f"{k} precisa ter exatamente {CATEGORIES}")
    for c in CATEGORIES:
        _num(r["risk_pct"], c, hi=5)
        _num(r["max_exposure_pct"], c, hi=100, nullable=True)
        _num(r["stop_max_pct"], c, hi=50)
        _num(r["slippage_pct"], c, hi=5)
    for k in ("stops", "window_h", "pause_h"):
        _num(r["stoploss_guard"], k)
    for k in ("min_samples", "seek_expectancy_r"):
        _num(r["setup_stats"], k)
    _num(r["setup_stats"], "avoid_expectancy_r", lo=-10)


def validate_universe(u: dict) -> None:
    if u.get("quote") != "USDT":
        raise ConfigError("quote suportado: USDT")
    for k in ("majors", "memes", "blacklist"):
        if not all(isinstance(x, str) and re.fullmatch(r"[A-Z0-9]{2,15}", x) for x in u.get(k, [])):
            raise ConfigError(f"{k} com ativo inválido")
    for c in CATEGORIES:
        _num(u["filters"]["min_listing_days"], c)
        if set(u["scan"]["weights"][c]) != {"trend", "breakout", "momentum", "volume"}:
            raise ConfigError(f"scan.weights.{c} incompleto")


@dataclass(frozen=True)
class Config:
    risk: MappingProxyType
    universe: MappingProxyType

    def category(self, symbol: str) -> str:
        base = symbol.split("/")[0]
        if base in self.universe["majors"]:
            return "major"
        if base in self.universe["memes"]:
            return "meme"
        return "alt"


def load_config(config_dir: Path = CONFIG_DIR) -> Config:
    risk = yaml.safe_load((config_dir / "risk.yaml").read_text(encoding="utf-8"))
    universe = yaml.safe_load((config_dir / "universe.yaml").read_text(encoding="utf-8"))
    validate_risk(risk)
    validate_universe(universe)
    return Config(_freeze(risk), _freeze(universe))


def load_secrets(config_dir: Path = CONFIG_DIR) -> dict:
    """Segredos: config/.env, com fallback para variáveis de ambiente. Nunca sai por tool/log."""
    env = dotenv_values(config_dir / ".env")
    keys = ("BINANCE_API_KEY", "BINANCE_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    return {k: (env.get(k) or os.environ.get(k) or "") for k in keys}


def valid_symbol(symbol: str) -> bool:
    return isinstance(symbol, str) and bool(SYMBOL_RE.fullmatch(symbol))
