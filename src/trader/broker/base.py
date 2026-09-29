"""Interface de corretora para derivativos com posição comprada/vendida e SL/TP na própria ordem (B3/MT5).

A Binance spot (`binance_spot.Exchange`) NÃO implementa este Protocol: o modelo dela (compra spot + OPOCO/OCO)
é outro e o código cripto continua falando com ela direto. Tipos aqui são do projeto, não da API do MT5;
o adaptador (`broker/mt5.py`) converte.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

Side = Literal["long", "short"]


class BrokerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Account:
    number: int
    is_real: bool          # conta real (live só é permitido nela)
    currency: str
    balance: Decimal
    equity: Decimal
    trade_allowed: bool = True   # terminal com Algo Trading ligado e conta liberada para robô


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    tick_size: Decimal       # em pontos
    tick_value: Decimal      # R$ por tick por contrato
    volume_min: Decimal
    volume_step: Decimal
    tradeable: bool          # negociação plena (compra e venda)
    expiration: datetime | None = None


@dataclass(frozen=True)
class Bar:
    time: datetime         # abertura da barra, horário de Brasília
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Tick:
    time: datetime
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume: Decimal
    aggressor: Side | None = None   # None = corretora não informa agressão


@dataclass(frozen=True)
class Position:
    ticket: int
    symbol: str
    side: Side
    volume: Decimal
    price_open: Decimal
    sl: Decimal | None     # None = posição sem stop na corretora (o watchdog zera)
    tp: Decimal | None
    magic: int
    comment: str
    opened_at: datetime


@dataclass(frozen=True)
class Order:
    ticket: int
    symbol: str
    side: Side
    volume: Decimal
    price: Decimal | None  # None = a mercado
    sl: Decimal | None
    tp: Decimal | None
    magic: int
    comment: str


@dataclass(frozen=True)
class Fill:
    order_ticket: int
    position_ticket: int
    symbol: str
    side: Side
    volume: Decimal
    price: Decimal
    fee: Decimal
    time: datetime


class Broker(Protocol):
    def account(self) -> Account: ...
    def connected(self) -> bool: ...
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...
    # timeframe: 1m | 5m | 15m | 60m | 1d; a barra em formação vem por último
    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]: ...
    def ticks(self, symbol: str, since: datetime) -> list[Tick]: ...
    def last_tick(self, symbol: str) -> Tick: ...
    # {'bids': [(preço, volume)], 'asks': [...]} ou None se a corretora não entrega book
    def book(self, symbol: str) -> dict | None: ...
    def positions(self, symbol: str | None = None) -> list[Position]: ...
    def orders(self, symbol: str | None = None) -> list[Order]: ...
    # execuções que fecharam a posição (vazio se ainda aberta)
    def exit_fills(self, position_ticket: int) -> list[Fill]: ...

    # escrita: chamada SÓ depois do risk manager
    def place_entry(self, symbol: str, side: Side, volume: Decimal, sl: Decimal, tp: Decimal,
                    magic: int, comment: str) -> Fill:
        """Entrada a mercado com SL e TP no mesmo envio. Sem SL não existe entrada."""
        ...

    def modify_sl(self, position_ticket: int, sl: Decimal) -> None: ...
    def close_position(self, position_ticket: int, comment: str) -> Fill: ...
    def cancel_all(self, symbol: str | None = None) -> None: ...
