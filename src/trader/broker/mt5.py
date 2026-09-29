"""Adaptador do pacote oficial MetaTrader5 (Windows, terminal aberto e logado, Algo Trading ligado).

Nomes de função, campos e constantes conferidos no pacote MetaTrader5 5.0.6231.
[VERIFICAR na Clear]: horário do servidor = horário de Brasília (o smoke compara o relógio do último tick),
SL/TP aceitos na própria ordem a mercado em execução por bolsa (se não, trading_b3 põe o SL logo depois ou zera),
flags de agressão nos ticks e book.
"""
import time
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from trader.broker.base import Account, Bar, BrokerError, Fill, Order, Position, Side, SymbolSpec, Tick

TZ = ZoneInfo("America/Sao_Paulo")
TIMEFRAMES = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "60m": "TIMEFRAME_H1",
              "1d": "TIMEFRAME_D1"}
SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2   # bits de symbol_info.filling_mode (MQL5); não expostos no pacote


def D(x) -> Decimal:
    return Decimal(str(x))


def from_server(ts: float) -> datetime:
    """Epoch do MT5 = relógio do servidor escrito como se fosse UTC."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=TZ)


def to_server(dt: datetime) -> datetime:
    return dt.astimezone(TZ).replace(tzinfo=timezone.utc)


def _opt(x) -> Decimal | None:
    return D(x) if x else None


class MT5Broker:
    is_paper = False

    def __init__(self, mt5=None, *, magic: int, path: str | None = None, deviation: int = 10,
                 fill_wait_s: float = 5, sleep=time.sleep):
        if mt5 is None:
            import MetaTrader5 as mt5
        self.mt5, self.magic, self.path, self.deviation = mt5, magic, path, deviation
        self.fill_wait_s, self._sleep = fill_wait_s, sleep
        self._books: set[str] = set()

    # ---- infraestrutura -------------------------------------------------
    def connect(self) -> None:
        ok = self.mt5.initialize(self.path) if self.path else self.mt5.initialize()
        if not ok:
            raise BrokerError("MT5_INIT", f"initialize falhou: {self.mt5.last_error()}")

    def shutdown(self) -> None:
        self.mt5.shutdown()

    def _need(self, value, what: str):
        if value is None:
            raise BrokerError("MT5_ERROR", f"{what}: {self.mt5.last_error()}")
        return value

    def connected(self) -> bool:
        ti = self.mt5.terminal_info()
        return bool(ti and ti.connected)

    def account(self) -> Account:
        a = self._need(self.mt5.account_info(), "account_info")
        ti = self.mt5.terminal_info()
        return Account(number=int(a.login), is_real=a.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_REAL,
                       currency=a.currency, balance=D(a.balance), equity=D(a.equity),
                       trade_allowed=bool(ti and ti.trade_allowed and a.trade_allowed and a.trade_expert))

    # ---- leitura --------------------------------------------------------
    def symbol_spec(self, symbol: str) -> SymbolSpec:
        if not self.mt5.symbol_select(symbol, True):
            raise BrokerError("UNKNOWN_SYMBOL", f"{symbol}: {self.mt5.last_error()}")
        i = self._need(self.mt5.symbol_info(symbol), f"symbol_info {symbol}")
        return SymbolSpec(symbol=symbol, tick_size=D(i.trade_tick_size), tick_value=D(i.trade_tick_value),
                          volume_min=D(i.volume_min), volume_step=D(i.volume_step),
                          tradeable=i.trade_mode == self.mt5.SYMBOL_TRADE_MODE_FULL,
                          expiration=from_server(i.expiration_time) if i.expiration_time else None)

    def bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        tf = getattr(self.mt5, TIMEFRAMES[timeframe])
        rates = self._need(self.mt5.copy_rates_from_pos(symbol, tf, 0, count), f"copy_rates {symbol} {timeframe}")
        return [Bar(time=from_server(r["time"]), open=D(r["open"]), high=D(r["high"]), low=D(r["low"]),
                    close=D(r["close"]), volume=D(r["real_volume"] or r["tick_volume"])) for r in rates]

    def _tick(self, t) -> Tick:
        flags = int(t["flags"])
        aggr = "long" if flags & self.mt5.TICK_FLAG_BUY else "short" if flags & self.mt5.TICK_FLAG_SELL else None
        return Tick(time=from_server(t["time_msc"] / 1000), bid=D(t["bid"]), ask=D(t["ask"]), last=D(t["last"]),
                    volume=D(t["volume_real"] or t["volume"]), aggressor=aggr)

    def ticks(self, symbol: str, since: datetime) -> list[Tick]:
        raw = self._need(self.mt5.copy_ticks_from(symbol, to_server(since), 200_000, self.mt5.COPY_TICKS_TRADE),
                         f"copy_ticks {symbol}")
        return [self._tick(t) for t in raw]

    def last_tick(self, symbol: str) -> Tick:
        t = self._need(self.mt5.symbol_info_tick(symbol), f"symbol_info_tick {symbol}")
        return Tick(time=from_server(t.time_msc / 1000), bid=D(t.bid), ask=D(t.ask), last=D(t.last),
                    volume=D(t.volume))

    def book(self, symbol: str) -> dict | None:
        if symbol not in self._books:
            if not self.mt5.market_book_add(symbol):
                return None
            self._books.add(symbol)
        rows = self.mt5.market_book_get(symbol)
        if not rows:
            return None
        asks = [(D(r.price), D(r.volume_dbl or r.volume)) for r in rows if r.type == self.mt5.BOOK_TYPE_SELL]
        bids = [(D(r.price), D(r.volume_dbl or r.volume)) for r in rows if r.type == self.mt5.BOOK_TYPE_BUY]
        return {"bids": sorted(bids, reverse=True), "asks": sorted(asks)}

    def _side(self, pos_type) -> Side:
        return "long" if pos_type == self.mt5.POSITION_TYPE_BUY else "short"

    def _position(self, p) -> Position:
        return Position(ticket=int(p.ticket), symbol=p.symbol, side=self._side(p.type), volume=D(p.volume),
                        price_open=D(p.price_open), sl=_opt(p.sl), tp=_opt(p.tp), magic=int(p.magic),
                        comment=p.comment, opened_at=from_server(p.time_msc / 1000))

    def positions(self, symbol: str | None = None) -> list[Position]:
        raw = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
        return [self._position(p) for p in self._need(raw, "positions_get")]

    def orders(self, symbol: str | None = None) -> list[Order]:
        raw = self._need(self.mt5.orders_get(symbol=symbol) if symbol else self.mt5.orders_get(), "orders_get")
        buys = {self.mt5.ORDER_TYPE_BUY, self.mt5.ORDER_TYPE_BUY_LIMIT, self.mt5.ORDER_TYPE_BUY_STOP,
                self.mt5.ORDER_TYPE_BUY_STOP_LIMIT}
        return [Order(ticket=int(o.ticket), symbol=o.symbol, side="long" if o.type in buys else "short",
                      volume=D(o.volume_current), price=_opt(o.price_open), sl=_opt(o.sl), tp=_opt(o.tp),
                      magic=int(o.magic), comment=o.comment) for o in raw]

    def _fill(self, d) -> Fill:
        return Fill(order_ticket=int(d.order), position_ticket=int(d.position_id), symbol=d.symbol,
                    side="long" if d.type == self.mt5.DEAL_TYPE_BUY else "short", volume=D(d.volume),
                    price=D(d.price), fee=-D(d.commission) - D(d.fee), time=from_server(d.time_msc / 1000))

    def _deals(self, position_ticket: int, entries: tuple) -> list[Fill]:
        raw = self._need(self.mt5.history_deals_get(position=position_ticket), "history_deals_get")
        return [self._fill(d) for d in raw if d.entry in entries]

    def exit_fills(self, position_ticket: int) -> list[Fill]:
        m = self.mt5
        return self._deals(position_ticket, (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY, m.DEAL_ENTRY_INOUT))

    # ---- escrita (chamada SÓ depois do risk manager) --------------------
    def _filling(self, symbol: str) -> int:
        # [VERIFICAR na Clear] preferência FOK > IOC > RETURN conforme o que o símbolo aceita
        fm = self._need(self.mt5.symbol_info(symbol), "symbol_info").filling_mode
        if fm & SYMBOL_FILLING_FOK:
            return self.mt5.ORDER_FILLING_FOK
        if fm & SYMBOL_FILLING_IOC:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: dict, ok=None):
        m = self.mt5
        ok = ok or (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_DONE_PARTIAL, m.TRADE_RETCODE_PLACED)
        r = m.order_send(req)
        if r is None:
            raise BrokerError("MT5_SEND", f"order_send sem resposta: {m.last_error()}")
        if r.retcode not in ok:
            raise BrokerError(f"RETCODE_{r.retcode}", f"{r.comment} ({m.last_error()})")
        return r

    def _market(self, symbol: str, side: Side, volume, **extra) -> dict:
        m = self.mt5
        t = self._need(m.symbol_info_tick(symbol), "symbol_info_tick")
        return {"action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(volume),
                "type": m.ORDER_TYPE_BUY if side == "long" else m.ORDER_TYPE_SELL,
                "price": t.ask if side == "long" else t.bid, "deviation": self.deviation, "magic": self.magic,
                "type_time": m.ORDER_TIME_DAY, "type_filling": self._filling(symbol), **extra}

    def place_entry(self, symbol: str, side: Side, volume: Decimal, sl: Decimal, tp: Decimal,
                    magic: int, comment: str) -> Fill:
        req = self._market(symbol, side, volume, sl=float(sl), tp=float(tp), magic=magic, comment=comment[:31])
        before = {p.ticket for p in self.positions(symbol)}
        self._send(req)
        # execução por bolsa pode voltar PLACED: espera a posição nova aparecer (não depende do comment,
        # que em conta netting pode não ser preservado)
        deadline = time.monotonic() + self.fill_wait_s
        while True:
            for p in self.positions(symbol):
                if p.magic == magic and p.ticket not in before:
                    return Fill(order_ticket=0, position_ticket=p.ticket, symbol=symbol, side=side,
                                volume=p.volume, price=p.price_open, fee=Decimal(0), time=p.opened_at)
            if time.monotonic() > deadline:
                raise BrokerError("NO_FILL", f"ordem aceita mas posição não apareceu em {self.fill_wait_s}s")
            self._sleep(0.25)

    def modify_sl(self, position_ticket: int, sl: Decimal) -> None:
        m = self.mt5
        pos = self._need(m.positions_get(ticket=position_ticket), "positions_get")
        if not pos:
            raise BrokerError("NO_POSITION", f"posição {position_ticket} não existe")
        p = pos[0]
        self._send({"action": m.TRADE_ACTION_SLTP, "symbol": p.symbol, "position": position_ticket,
                    "sl": float(sl), "tp": p.tp, "magic": self.magic},
                   ok=(m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_NO_CHANGES, m.TRADE_RETCODE_PLACED))

    def close_position(self, position_ticket: int, comment: str) -> Fill:
        m = self.mt5
        pos = self._need(m.positions_get(ticket=position_ticket), "positions_get")
        if not pos:
            raise BrokerError("NO_POSITION", f"posição {position_ticket} não existe")
        p = pos[0]
        opposite = "short" if p.type == m.POSITION_TYPE_BUY else "long"
        self._send(self._market(p.symbol, opposite, p.volume, position=position_ticket, comment=comment[:31]))
        deadline = time.monotonic() + self.fill_wait_s
        while True:
            fills = self.exit_fills(position_ticket)
            if fills and sum(f.volume for f in fills) >= D(p.volume):
                return fills[-1]
            if time.monotonic() > deadline:
                raise BrokerError("NO_FILL", f"zeragem enviada mas sem execução em {self.fill_wait_s}s")
            self._sleep(0.25)

    def cancel_all(self, symbol: str | None = None) -> None:
        for o in self.orders(symbol):
            self._send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": o.ticket},
                       ok=(self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED))
