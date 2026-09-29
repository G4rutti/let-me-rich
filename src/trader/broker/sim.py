"""Corretora de papel: mesma interface Broker, ordens nunca saem daqui.

- SimBroker(data): dados de mercado de outra fonte (MT5 real em `dry`, ou Replay); posições em memória,
  SL/TP avaliados a cada leitura contra o último tick. Stop executa no bid/ask (pior que o stop se houve gap),
  alvo executa no preço do alvo.
- Replay: fonte de dados sobre barras 1m gravadas (smoke e backtest futuro).
"""
import itertools
from datetime import datetime, timedelta
from decimal import Decimal

from trader.broker.base import Account, Bar, BrokerError, Fill, Position, Side, SymbolSpec, Tick

TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "60m": 60, "1d": 1440}


def resample(bars_1m: list[Bar], minutes: int) -> list[Bar]:
    """Agrupa barras 1m por janela alinhada ao relógio (60m = hora cheia, 1d = dia)."""
    out: list[Bar] = []
    for b in bars_1m:
        if minutes >= 1440:
            start = b.time.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            m = (b.time.hour * 60 + b.time.minute) // minutes * minutes
            start = b.time.replace(hour=m // 60, minute=m % 60, second=0, microsecond=0)
        if out and out[-1].time == start:
            o = out[-1]
            out[-1] = Bar(start, o.open, max(o.high, b.high), min(o.low, b.low), b.close, o.volume + b.volume)
        else:
            out.append(Bar(start, b.open, b.high, b.low, b.close, b.volume))
    return out


class Replay:
    """Anda por barras 1m gravadas; o 'tick' atual é o fechamento da barra corrente com spread fixo."""

    def __init__(self, bars_1m: list[Bar], symbol: str, spread: Decimal = Decimal(5), spec: SymbolSpec | None = None):
        self._bars, self.symbol, self.spread, self.i = bars_1m, symbol, spread, 0
        self._spec = spec or SymbolSpec(symbol, Decimal(5), Decimal(1), Decimal(1), Decimal(1), True)

    def advance(self) -> bool:
        if self.i + 1 >= len(self._bars):
            return False
        self.i += 1
        return True

    @property
    def now(self) -> datetime:
        return self._bars[self.i].time + timedelta(minutes=1)

    def connected(self) -> bool:
        return True

    def account(self) -> Account:
        return Account(0, False, "BRL", Decimal(0), Decimal(0))

    def symbol_spec(self, symbol: str) -> SymbolSpec:
        return self._spec

    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        seen = self._bars[: self.i + 1]
        return resample(seen, TF_MIN[timeframe])[-count:] if timeframe != "1m" else seen[-count:]

    def ticks(self, symbol: str, since: datetime) -> list[Tick]:
        return []

    def last_tick(self, symbol: str) -> Tick:
        b = self._bars[self.i]
        return Tick(self.now, b.close - self.spread, b.close, b.close, Decimal(0))

    def book(self, symbol: str) -> dict | None:
        return None


class SimBroker:
    is_paper = True

    def __init__(self, data, start_balance: Decimal = Decimal(0)):
        self.data = data
        self.balance = start_balance
        self._pos: dict[int, dict] = {}
        self._exits: dict[int, list[Fill]] = {}
        self._ids = itertools.count(1)

    # leitura: mercado vem da fonte de dados
    def connected(self) -> bool:
        return self.data.connected()

    def account(self) -> Account:
        return Account(0, False, "BRL", self.balance, self.balance)

    def symbol_spec(self, symbol):
        return self.data.symbol_spec(symbol)

    def bars(self, symbol, timeframe, count):
        return self.data.bars(symbol, timeframe, count)

    def ticks(self, symbol, since):
        return self.data.ticks(symbol, since)

    def book(self, symbol):
        return self.data.book(symbol)

    def last_tick(self, symbol) -> Tick:
        t = self.data.last_tick(symbol)
        self._mark(symbol, t)
        return t

    def restore(self, position: Position) -> None:
        """Reidrata uma posição de papel a partir do banco (executor reiniciado)."""
        self._pos[position.ticket] = {"p": position}
        self._ids = itertools.count(max(self._pos) + 1)

    def _mark(self, symbol: str, t: Tick) -> None:
        for ticket, rec in list(self._pos.items()):
            p = rec["p"]
            if p.symbol != symbol:
                continue
            long_ = p.side == "long"
            px = t.bid if long_ else t.ask
            if p.sl is not None and ((px <= p.sl) if long_ else (px >= p.sl)):
                self._close(p, px, t.time)
            elif p.tp is not None and ((px >= p.tp) if long_ else (px <= p.tp)):
                self._close(p, p.tp, t.time)

    def _close(self, p: Position, price: Decimal, when: datetime) -> Fill:
        f = Fill(0, p.ticket, p.symbol, "short" if p.side == "long" else "long", p.volume, price, Decimal(0), when)
        self._exits.setdefault(p.ticket, []).append(f)
        del self._pos[p.ticket]
        return f

    def positions(self, symbol: str | None = None) -> list[Position]:
        for s in {r["p"].symbol for r in self._pos.values()}:
            self._mark(s, self.data.last_tick(s))
        return [r["p"] for r in self._pos.values() if symbol is None or r["p"].symbol == symbol]

    def orders(self, symbol=None):
        return []

    def exit_fills(self, position_ticket: int) -> list[Fill]:
        return list(self._exits.get(position_ticket, []))

    # escrita
    def place_entry(self, symbol: str, side: Side, volume: Decimal, sl: Decimal, tp: Decimal,
                    magic: int, comment: str) -> Fill:
        t = self.data.last_tick(symbol)
        price = t.ask if side == "long" else t.bid
        ticket = next(self._ids)
        self._pos[ticket] = {"p": Position(ticket, symbol, side, Decimal(volume), price, Decimal(sl), Decimal(tp),
                                           magic, comment, t.time)}
        return Fill(ticket, ticket, symbol, side, Decimal(volume), price, Decimal(0), t.time)

    def modify_sl(self, position_ticket: int, sl: Decimal) -> None:
        rec = self._pos.get(position_ticket)
        if not rec:
            raise BrokerError("NO_POSITION", f"posição {position_ticket} não existe")
        p = rec["p"]
        rec["p"] = Position(p.ticket, p.symbol, p.side, p.volume, p.price_open, Decimal(sl), p.tp, p.magic,
                            p.comment, p.opened_at)

    def close_position(self, position_ticket: int, comment: str) -> Fill:
        rec = self._pos.get(position_ticket)
        if not rec:
            raise BrokerError("NO_POSITION", f"posição {position_ticket} não existe")
        p = rec["p"]
        t = self.data.last_tick(p.symbol)
        return self._close(p, t.bid if p.side == "long" else t.ask, t.time)

    def cancel_all(self, symbol=None) -> None:
        pass
