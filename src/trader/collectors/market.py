"""Contexto externo (futuro do S&P, EWZ, dólar, petróleo, minério...) via endpoint público de gráfico do Yahoo.

Coletado em Python; o operador nunca acessa a web. Fonte falhou = campo "indisponível", o dia segue.
"""
from pathlib import Path

import httpx
import yaml

from trader.config import CONFIG_DIR

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
NA = "indisponível"


def sources(config_dir: Path = CONFIG_DIR) -> dict:
    return yaml.safe_load((config_dir / "b3_sources.yaml").read_text(encoding="utf-8")) or {}


def quote(ticker: str, get=httpx.get) -> dict | str:
    """Último fechamento, anterior e variação % (5 dias diários)."""
    try:
        r = get(URL.format(ticker=ticker), params={"range": "5d", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res = r.json()["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        last = res["meta"].get("regularMarketPrice") or closes[-1]
        prev = closes[-2] if len(closes) >= 2 else None
        return {"last": round(last, 4), "prev_close": round(prev, 4) if prev else None,
                "change_pct": round((last / prev - 1) * 100, 2) if prev else None}
    except Exception:  # noqa: BLE001 — qualquer falha de fonte vira "indisponível"
        return NA


def collect(get=httpx.get, config_dir: Path = CONFIG_DIR) -> dict:
    return {name: quote(t, get) for name, t in (sources(config_dir).get("market") or {}).items()}
