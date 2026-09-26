"""Risk manager. Funções puras: sem I/O, sem exchange, sem banco. Toda ordem passa por aqui antes de sair.

O Claude NUNCA informa tamanho: check_entry calcula a quantidade a partir do risco da categoria e da distância do stop.
Qualquer dúvida = recusa. Tamanho nunca é aumentado para caber em mínimo da exchange.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trader.exchange import D, MarketRules


@dataclass(frozen=True)
class Rejected:
    code: str
    hint: str
    ok: bool = False


@dataclass(frozen=True)
class Approved:
    qty: Decimal
    limit_price: Decimal
    stop: Decimal
    target: Decimal
    notional: Decimal
    risk_usd: Decimal
    ok: bool = True


@dataclass(frozen=True)
class Position:
    symbol: str
    category: str
    value_usd: Decimal


@dataclass
class RiskState:
    equity_usd: Decimal                 # banca total (USDT + posições a mercado)
    free_usdt: Decimal
    day_start_equity: Decimal
    realized_today: Decimal = D(0)      # PnL realizado no dia (fuso da config), líquido
    trades_today: int = 0
    notional_today: Decimal = D(0)
    positions: list[Position] = field(default_factory=list)
    last_stop_at: dict[str, datetime] = field(default_factory=dict)   # símbolo -> último stop tomado
    recent_stops: list[datetime] = field(default_factory=list)        # stops de qualquer moeda
    consecutive_order_failures: int = 0
    paused: bool = False
    regime: str = "NEUTRO"
    setup_status: str = "NEUTRO"        # PROCURAR | NEUTRO | EVITAR (do setup proposto)


def day_start(now: datetime, tz: str) -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def gate(cfg: dict, st: RiskState, now: datetime) -> Rejected | None:
    """Travas globais que valem para qualquer entrada nova."""
    if cfg["mode"] == "off":
        return Rejected("MODE_OFF", "risk.yaml mode=off: nenhuma ordem")
    if st.paused:
        return Rejected("PAUSED", "bot pausado (/resume no Telegram)")
    if st.consecutive_order_failures >= cfg["max_consecutive_order_failures"]:
        return Rejected("CIRCUIT_BREAKER", "falhas de ordem seguidas; exige reset manual")
    g = cfg["stoploss_guard"]
    window = [t for t in st.recent_stops if now - t <= timedelta(hours=g["window_h"])]
    if len(window) >= g["stops"] and now - max(window) < timedelta(hours=g["pause_h"]):
        return Rejected("STOPLOSS_GUARD", f"{len(window)} stops em {g['window_h']}h; pausa de {g['pause_h']}h")
    if st.realized_today <= -st.day_start_equity * D(cfg["daily_loss_max_pct"]) / 100:
        return Rejected("DAILY_LOSS_HIT", "perda diária máxima atingida; volta amanhã")
    if st.trades_today >= cfg["max_trades_per_day"]:
        return Rejected("MAX_TRADES_DAY", "limite de trades do dia")
    return None


def check_entry(cfg: dict, st: RiskState, rules: MarketRules, *, category: str, ask, stop, target,
                atr, now: datetime) -> Approved | Rejected:
    if (r := gate(cfg, st, now)) is not None:
        return r
    sym = rules.symbol
    if not rules.active:
        return Rejected("MARKET_INACTIVE", f"{sym} não está em TRADING")
    if not (rules.opo_allowed or rules.oco_allowed):
        return Rejected("NO_PROTECTION", f"{sym} não aceita OCO; sem stop na exchange não entra")
    if any(p.symbol == sym for p in st.positions):
        return Rejected("DUPLICATE_POSITION", f"já existe posição em {sym}")
    if len(st.positions) >= cfg["max_open_positions"]:
        return Rejected("MAX_POSITIONS", f"máximo de {cfg['max_open_positions']} posições")
    if st.regime == "BEAR" and cfg["bear_blocks"][category]:
        return Rejected("REGIME_BEAR", f"regime BEAR bloqueia {category}")
    last = st.last_stop_at.get(sym)
    if last and now - last < timedelta(hours=cfg["cooldown_after_stop_h"]):
        return Rejected("COOLDOWN", f"{sym} tomou stop há menos de {cfg['cooldown_after_stop_h']}h")
    if st.setup_status == "EVITAR":
        return Rejected("SETUP_AVOID", "setup marcado EVITAR pelas estatísticas")

    ask, atr = D(ask), (D(atr) if atr else None)
    if ask <= 0 or D(stop) <= 0 or D(target) <= 0:
        return Rejected("BAD_PRICE", "preços devem ser positivos")
    fee, slip = D(cfg["fee_pct"]) / 100, D(cfg["slippage_pct"][category]) / 100
    entry = rules.ceil_price(ask * (1 + slip))          # limite de compra marketable
    if entry > ask * (1 + D(cfg["max_entry_premium_pct"]) / 100):
        return Rejected("PRICE_SANITY", "limite de compra longe demais do ask")
    stop, target = rules.floor_price(stop), rules.floor_price(target)
    if stop >= entry:
        return Rejected("STOP_ABOVE_ENTRY", f"stop {stop} precisa ficar abaixo da entrada {entry}")
    if target <= entry:
        return Rejected("TARGET_BELOW_ENTRY", f"alvo {target} precisa ficar acima da entrada {entry}")
    stop_pct = (entry - stop) / entry * 100
    if stop_pct < D(cfg["stop_min_pct"]):
        return Rejected("STOP_TOO_TIGHT", f"stop a {stop_pct:.2f}% < mínimo {cfg['stop_min_pct']}%")
    if stop_pct > D(cfg["stop_max_pct"][category]):
        return Rejected("STOP_TOO_WIDE", f"stop a {stop_pct:.2f}% > máximo {cfg['stop_max_pct'][category]}% ({category})")
    if atr is None or atr <= 0:
        return Rejected("NO_ATR", "ATR indisponível; sem medida de volatilidade não entra")
    if entry - stop > atr * D(cfg["max_stop_atr"]):
        return Rejected("STOP_TOO_WIDE_ATR", f"stop a {(entry - stop) / atr:.1f} ATR > {cfg['max_stop_atr']}")
    rr = (target - entry) / (entry - stop)
    if rr < D(cfg["min_rr"]):
        return Rejected("RR_TOO_LOW", f"R:R {rr:.2f} < {cfg['min_rr']}")
    move_pct = (target - entry) / entry * 100
    cost_pct = (2 * fee + slip) * 100
    if move_pct < cost_pct * D(cfg["min_move_fee_multiple"]):
        return Rejected("FEES_EAT_TARGET", f"alvo a {move_pct:.2f}% < {cfg['min_move_fee_multiple']}x custo ({cost_pct:.2f}%)")
    if target > ask * rules.ask_mult_up:
        return Rejected("TARGET_OUT_OF_BAND", "alvo fora do PERCENT_PRICE_BY_SIDE da exchange")

    # ---- sizing: risco fixo da categoria / perda por unidade (inclui taxas e slippage do stop a mercado)
    risk_usd = st.equity_usd * D(cfg["risk_pct"][category]) / 100
    loss_per_unit = (entry - stop) + (entry + stop) * fee + stop * slip
    notional = risk_usd / loss_per_unit * entry
    caps = {
        "max_position_pct": st.equity_usd * D(cfg["max_position_pct"]) / 100,
        "max_order_usd": D(cfg["max_order_usd"]),
        "saldo_livre": st.free_usdt * D("0.99"),
        "max_daily_notional": D(cfg["max_daily_notional_usd"]) - st.notional_today,
    }
    exp_cap = cfg["max_exposure_pct"][category]
    if exp_cap is not None:
        used = sum((p.value_usd for p in st.positions if p.category == category), D(0))
        caps["exposicao_" + category] = st.equity_usd * D(exp_cap) / 100 - used
    notional = min(notional, *caps.values())
    qty = rules.floor_qty(max(notional, D(0)) / entry)
    notional = qty * entry
    need = rules.min_notional * D(cfg["min_notional_buffer"])
    if qty < rules.min_qty or notional < need:
        binding = min(caps, key=caps.get)
        return Rejected("BELOW_MIN_NOTIONAL",
                        f"tamanho {notional:.2f} USDT < mínimo {need:.2f} (limite ativo: {binding}); não aumento o tamanho")
    if qty * (1 - fee) * stop < rules.min_notional:
        return Rejected("STOP_LEG_BELOW_MIN", "perna de stop ficaria abaixo do min notional")
    return Approved(qty=qty, limit_price=entry, stop=stop, target=target, notional=notional,
                    risk_usd=qty * loss_per_unit)


def check_move_stop(rules: MarketRules, current_stop, new_stop, last_price) -> Decimal | Rejected:
    new = rules.floor_price(new_stop)
    if new <= D(current_stop):
        return Rejected("STOP_ONLY_UP", f"stop só sobe: atual {current_stop}, pedido {new}")
    if new >= D(last_price) - rules.tick:
        return Rejected("STOP_ABOVE_PRICE", f"stop {new} precisa ficar abaixo do preço {last_price}")
    return new


def check_new_target(rules: MarketRules, stop, new_target, last_price) -> Decimal | Rejected:
    t = rules.floor_price(new_target)
    if t <= D(last_price) + rules.tick or t <= D(stop):
        return Rejected("TARGET_BELOW_PRICE", "alvo precisa ficar acima do preço atual")
    return t


def check_partial(cfg: dict, rules: MarketRules, qty, fraction, price) -> Decimal | Rejected:
    """Retorna a quantidade a vender. Parte vendida e restante precisam ser vendáveis depois."""
    fraction, qty, price = D(fraction), D(qty), D(price)
    if not (D("0.1") <= fraction <= D("0.9")):
        return Rejected("BAD_FRACTION", "fração entre 0.1 e 0.9 (para fechar tudo use close_position)")
    sell = rules.floor_qty(qty * fraction, market=True)
    need = rules.min_notional * D(cfg["partial_min_notional_buffer"])
    if sell * price < need or (qty - sell) * price < need:
        return Rejected("PARTIAL_BELOW_MIN", f"parte ou restante < {need:.2f} USDT; feche a posição inteira")
    return sell
