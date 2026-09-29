"""Contrato vigente do mini-índice, vencimento e conferência das especificações com o MT5.

Vencimento do WIN: meses pares, quarta-feira mais próxima do dia 15 [VERIFICAR regra B3; feriado adia].
Quando o MT5 informa `expiration_time`, ele é a fonte da verdade e a regra local vira só conferência.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from trader.broker.base import SymbolSpec

MONTH_CODE = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
EXPIRY_MONTHS = (2, 4, 6, 8, 10, 12)


@dataclass(frozen=True)
class Contract:
    symbol: str
    expiry: date


def expiry_date(year: int, month: int) -> date:
    d15 = date(year, month, 15)
    diff = 2 - d15.weekday()          # quarta = 2
    if diff > 3:
        diff -= 7
    elif diff < -3:
        diff += 7
    return d15 + timedelta(days=diff)


def contract(root: str, year: int, month: int) -> Contract:
    return Contract(f"{root}{MONTH_CODE[month]}{year % 100:02d}", expiry_date(year, month))


def business_days_until(today: date, until: date) -> int:
    """Dias úteis (seg-sex) depois de `today` até `until`, inclusive. Feriados ignorados."""
    # ponytail: sem calendário de feriados B3; roll_days pequeno absorve o erro de 1 dia
    n, d = 0, today
    while d < until:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


def upcoming(root: str, today: date, n: int = 3) -> list[Contract]:
    out, y, m = [], today.year, today.month
    while len(out) < n:
        if m in EXPIRY_MONTHS and expiry_date(y, m) >= today:
            out.append(contract(root, y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def current_contract(root: str, today: date, roll_days: int) -> Contract:
    """Contrato em que se opera hoje: rola para o próximo quando faltam <= roll_days dias úteis."""
    first, second = upcoming(root, today, 2)
    if first.expiry == today or business_days_until(today, first.expiry) <= roll_days:
        return second
    return first


def is_expiry_day(root: str, today: date, broker_expiry: date | None = None) -> bool:
    return today == (broker_expiry or upcoming(root, today, 1)[0].expiry)


def check_spec(cfg, spec: SymbolSpec, expected: Contract) -> tuple[list[str], list[str]]:
    """(problemas, avisos). Qualquer problema = não opera."""
    i = cfg["instrument"]
    problems, warnings = [], []
    if spec.tick_size != Decimal(str(i["tick_points"])):
        problems.append(f"tick do MT5 {spec.tick_size} != config {i['tick_points']}")
    elif spec.tick_size > 0 and abs(spec.tick_value / spec.tick_size - Decimal(str(i["point_value_brl"]))) > Decimal("1e-9"):
        problems.append(f"valor do ponto MT5 {spec.tick_value / spec.tick_size} != config {i['point_value_brl']}")
    if spec.volume_min > 1 or spec.volume_step != 1:
        problems.append(f"volume_min={spec.volume_min} volume_step={spec.volume_step}: esperado 1/1")
    if not spec.tradeable:
        problems.append(f"{spec.symbol} não está com negociação plena")
    if spec.expiration and spec.expiration.date() != expected.expiry:
        warnings.append(f"vencimento MT5 {spec.expiration.date()} != regra local {expected.expiry}; vale o do MT5")
    return problems, warnings
