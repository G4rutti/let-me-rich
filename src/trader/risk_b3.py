"""Risk manager do WIN. Funções puras: sem I/O, sem corretora, sem banco. Toda entrada passa por check_entry.

Tamanho nunca vem da IA: contratos = floor((risco - custo) / (pontos_stop x valor_ponto)), 0 = recusa, teto 1.
Qualquer dúvida = recusa.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from trader.b3.config import cost_brl, hhmm

Side = Literal["long", "short"]
LEVELS = ("normal", "reduzido", "fora")


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


@dataclass(frozen=True)
class Rejected:
    code: str
    hint: str
    ok: bool = False


@dataclass(frozen=True)
class Approved:
    side: Side
    contracts: int
    entry: Decimal          # preço de referência (ask na compra, bid na venda)
    sl: Decimal
    tp: Decimal
    stop_points: Decimal
    risk_brl: Decimal       # perda no stop planejado, custos incluídos
    ok: bool = True


@dataclass
class DayState:
    realized_today_brl: Decimal = D(0)     # líquido, custos incluídos
    open_pnl_brl: Decimal = D(0)
    total_pnl_brl: Decimal = D(0)          # desde capital_start (realizado + aberto)
    trades_today: int = 0
    entries_by_setup: dict[str, int] = field(default_factory=dict)
    open_position: bool = False
    last_stop_at: datetime | None = None
    consecutive_order_failures: int = 0
    paused: bool = False
    halted_today: bool = False             # trava de perda diária acionada hoje
    halted_total: bool = False
    risk_level: str = "normal"
    bias: str = "neutral"                  # long | short | neutral
    setup_status: str = "NEUTRO"           # PROCURAR | NEUTRO | EVITAR


def round_tick(price, tick, mode) -> Decimal:
    t = D(tick)
    return (D(price) / t).to_integral_value(mode) * t


def loss_action(cfg, st: DayState) -> str | None:
    """'total' | 'day' | None. Perda aberta conta."""
    r = cfg["risk"]
    if st.halted_total or -st.total_pnl_brl >= D(r["total_loss_max_brl"]):
        return "total"
    if st.halted_today or -(st.realized_today_brl + st.open_pnl_brl) >= D(r["daily_loss_max_brl"]):
        return "day"
    return None


def gate(cfg, st: DayState, now: datetime) -> Rejected | None:
    """Travas que valem para qualquer entrada, independentes do setup."""
    r = cfg["risk"]
    if cfg["mode"] == "off":
        return Rejected("MODE_OFF", "b3.yaml mode=off")
    if st.paused:
        return Rejected("PAUSED", "bot pausado (/resume no Telegram)")
    if st.consecutive_order_failures >= r["max_consecutive_order_failures"]:
        return Rejected("CIRCUIT_BREAKER", "falhas de ordem seguidas; exige reset manual")
    act = loss_action(cfg, st)
    if act == "total":
        return Rejected("TOTAL_LOSS_HIT", "perda total máxima atingida; só religa à mão")
    if act == "day":
        return Rejected("DAILY_LOSS_HIT", "perda diária máxima atingida; volta no próximo pregão")
    if st.risk_level == "fora":
        return Rejected("RISK_FORA", "risk_level=fora: dia sem operação")
    if st.open_position:
        return Rejected("OPEN_POSITION", "já existe posição aberta; uma por vez")
    max_trades = cfg["reduced_day"]["max_trades_per_day"] if st.risk_level == "reduzido" else r["max_trades_per_day"]
    if st.trades_today >= max_trades:
        return Rejected("MAX_TRADES_DAY", f"limite de {max_trades} trade(s) no dia ({st.risk_level})")
    if st.last_stop_at and now - st.last_stop_at < timedelta(minutes=r["cooldown_after_stop_min"]):
        return Rejected("COOLDOWN", f"stop há menos de {r['cooldown_after_stop_min']} min")
    t = now.time()
    s = cfg["session"]
    if t < hhmm(s["no_entry_before"]) or t >= hhmm(s["no_entry_after"]):
        return Rejected("OUTSIDE_WINDOW", f"entradas só entre {s['no_entry_before']} e {s['no_entry_after']}")
    return None


def check_entry(cfg, st: DayState, *, side: Side, setup_id: str, max_entries: int, bid, ask, stop, target,
                atr5m, now: datetime, expiry_day: bool = False,
                events: tuple[datetime, ...] = ()) -> Approved | Rejected:
    if side not in ("long", "short"):
        return Rejected("BAD_SIDE", "direção deve ser long ou short")
    if (g := gate(cfg, st, now)) is not None:
        return g
    r, i, rd, f = cfg["risk"], cfg["instrument"], cfg["reduced_day"], cfg["filters"]
    reduced = st.risk_level == "reduzido"
    if st.entries_by_setup.get(setup_id, 0) >= max_entries:
        return Rejected("MAX_ENTRIES_SETUP", f"setup {setup_id} já usou suas {max_entries} entrada(s)")
    if expiry_day and f["block_expiry_day"]:
        return Rejected("EXPIRY_DAY", "dia de vencimento do contrato: não opera")
    w = timedelta(minutes=f["block_event_window_min"])
    for ev in events:
        if abs(now - ev) <= w:
            return Rejected("EVENT_WINDOW", f"evento de alto impacto às {ev:%H:%M} (janela ±{f['block_event_window_min']} min)")
    if st.setup_status == "EVITAR":
        return Rejected("SETUP_AVOID", "setup marcado EVITAR pelas estatísticas")
    if reduced and rd["only_with_bias"] and st.bias != side:
        return Rejected("AGAINST_BIAS", f"dia reduzido: só a favor do bias ({st.bias})")

    tick, pv = D(i["tick_points"]), D(i["point_value_brl"])
    bid, ask = D(bid), D(ask)
    if bid <= 0 or ask <= 0 or ask < bid or D(stop) <= 0 or D(target) <= 0:
        return Rejected("BAD_PRICE", "preços inválidos")
    if (ask - bid) > tick * f["max_spread_ticks"]:
        return Rejected("SPREAD", f"spread {ask - bid} > {f['max_spread_ticks']} ticks")
    long_ = side == "long"
    entry = ask if long_ else bid
    # stop arredondado para longe da entrada (conservador), alvo para perto
    sl = round_tick(stop, tick, ROUND_FLOOR if long_ else ROUND_CEILING)
    tp = round_tick(target, tick, ROUND_FLOOR if long_ else ROUND_CEILING)
    if (sl >= entry) if long_ else (sl <= entry):
        return Rejected("STOP_WRONG_SIDE", f"stop {sl} do lado errado da entrada {entry} ({side})")
    if (tp <= entry) if long_ else (tp >= entry):
        return Rejected("TARGET_WRONG_SIDE", f"alvo {tp} do lado errado da entrada {entry} ({side})")
    pts, reward = abs(entry - sl), abs(tp - entry)
    stop_max = rd["stop_max_points"] if reduced else r["stop_max_points"]
    if pts < r["stop_min_points"]:
        return Rejected("STOP_TOO_TIGHT", f"stop de {pts} pts < mínimo {r['stop_min_points']}")
    if pts > stop_max:
        return Rejected("STOP_TOO_WIDE", f"stop de {pts} pts > máximo {stop_max} ({st.risk_level})")
    if not atr5m or D(atr5m) <= 0:
        return Rejected("NO_ATR", "ATR 5m indisponível")
    if pts > D(atr5m) * D(r["max_stop_atr"]):
        return Rejected("STOP_TOO_WIDE_ATR", f"stop {pts / D(atr5m):.2f} ATR5m > {r['max_stop_atr']}")
    if reward / pts < D(r["min_rr"]):
        return Rejected("RR_TOO_LOW", f"R:R {reward / pts:.2f} < {r['min_rr']}")
    cost = D(cost_brl(cfg))
    if reward * pv < cost * D(r["min_target_cost_multiple"]):
        return Rejected("COSTS_EAT_TARGET", f"alvo vale R${reward * pv:.2f} < {r['min_target_cost_multiple']}x custo R${cost:.2f}")
    contracts = math.floor((D(r["risk_per_trade_brl"]) - cost) / (pts * pv))
    if contracts < 1:
        return Rejected("SIZE_ZERO", "stop não cabe no risco por trade com 1 contrato; não aumento para caber")
    contracts = min(contracts, 1, r["max_contracts_hard"])
    risk = pts * pv * contracts + cost
    day_left = D(r["daily_loss_max_brl"]) + st.realized_today_brl + st.open_pnl_brl
    if risk > day_left:
        return Rejected("DAILY_RISK_LEFT", f"risco R${risk:.2f} > resta no limite diário R${day_left:.2f}")
    total_left = D(r["total_loss_max_brl"]) + st.total_pnl_brl
    if risk > total_left:
        return Rejected("TOTAL_RISK_LEFT", f"risco R${risk:.2f} > resta no limite total R${total_left:.2f}")
    return Approved(side=side, contracts=contracts, entry=entry, sl=sl, tp=tp, stop_points=pts, risk_brl=risk)


def check_move_stop(cfg, side: Side, current_sl, new_sl, bid, ask) -> Decimal | Rejected:
    """Stop só anda a favor e fica do lado certo do preço (com 1 tick de folga)."""
    tick = D(cfg["instrument"]["tick_points"])
    long_ = side == "long"
    new = round_tick(new_sl, tick, ROUND_FLOOR if long_ else ROUND_CEILING)
    cur = D(current_sl)
    if (new <= cur) if long_ else (new >= cur):
        return Rejected("STOP_ONLY_FAVOR", f"stop só anda a favor: atual {cur}, pedido {new}")
    if (new >= D(bid) - tick) if long_ else (new <= D(ask) + tick):
        return Rejected("STOP_BEYOND_PRICE", f"stop {new} passaria do preço atual")
    return new


def breakeven_stop(side: Side, entry, initial_sl, current_sl, bid, ask) -> Decimal | None:
    """Com +1R, stop no preço de entrada. None = nada a fazer."""
    entry, r = D(entry), abs(D(entry) - D(initial_sl))
    if side == "long":
        return entry if D(bid) - entry >= r and D(current_sl) < entry else None
    return entry if entry - D(ask) >= r and D(current_sl) > entry else None


def pnl_brl(cfg, side: Side, entry, exit_price, contracts: int = 1, costs: bool = True) -> Decimal:
    pts = (D(exit_price) - D(entry)) * (1 if side == "long" else -1)
    gross = pts * D(cfg["instrument"]["point_value_brl"]) * contracts
    return gross - (D(cfg["risk"]["costs_per_contract_brl"]) * contracts if costs else 0)


def send_allowed(cfg, account) -> tuple[bool, str]:
    """Ordem real só com config live + conta real + número esperado. Em dry nada é enviado."""
    if cfg["mode"] != "live":
        return False, f"mode={cfg['mode']}: nada é enviado"
    if account is None:
        return False, "sem conta MT5"
    if not account.is_real:
        return False, "conta logada não é real"
    if account.number != cfg["account_number"]:
        return False, f"conta logada {account.number} != account_number da config"
    return True, "live"
