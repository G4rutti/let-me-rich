"""Fake do pacote MetaTrader5: conta, símbolo, ticks, order_send com SL/TP, fills, rejeições, desconexão.

Constantes copiadas do pacote real (mesmos valores). Tempo em "epoch do servidor" = relógio de Brasília como UTC.
"""
import itertools
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import MetaTrader5 as _real

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc).timestamp()   # 10:00 em Brasília (horário do servidor)


class FakeMT5:
    def __init__(self, symbol="WINV26", bid=130000.0, ask=130005.0, login=42, real=True):
        for k in dir(_real):
            if k.isupper():
                setattr(self, k, getattr(_real, k))
        self.symbol = symbol
        self.bid, self.ask, self.now = bid, ask, T0
        self.acc = NS(login=login, trade_mode=self.ACCOUNT_TRADE_MODE_REAL if real else self.ACCOUNT_TRADE_MODE_DEMO,
                      currency="BRL", balance=100.0, equity=100.0, trade_allowed=True, trade_expert=True)
        self.term = NS(connected=True, trade_allowed=True)
        self.info = NS(trade_tick_size=5.0, trade_tick_value=1.0, volume_min=1.0, volume_step=1.0,
                       trade_mode=self.SYMBOL_TRADE_MODE_FULL, expiration_time=datetime(2026, 10, 14, 18, tzinfo=timezone.utc).timestamp(),
                       filling_mode=1)
        self.pos, self.ords, self.deals, self.sent = {}, {}, [], []
        self.rates = []
        self.ticks = []
        self._ids = itertools.count(1000)
        self.alive = True           # False = terminal caiu (tudo devolve None)
        self.reject = None          # retcode da próxima order_send
        self.drop_sl = False        # corretora aceita a entrada mas ignora o SL
        self.ignore_sltp = False    # TRADE_ACTION_SLTP responde DONE mas não muda nada
        self.hide_fills = 0         # posições novas ficam invisíveis por N consultas (execução PLACED)
        self._hidden = {}

    def last_error(self):
        return (1, "fake error")

    def initialize(self, *a, **k):
        return self.alive

    def shutdown(self):
        pass

    def terminal_info(self):
        return self.term if self.alive else None

    def account_info(self):
        return self.acc if self.alive else None

    def symbol_select(self, s, enable):
        return self.alive and s == self.symbol

    def symbol_info(self, s):
        return self.info if self.alive and s == self.symbol else None

    def symbol_info_tick(self, s):
        if not self.alive:
            return None
        return NS(time=int(self.now), time_msc=int(self.now * 1000), bid=self.bid, ask=self.ask, last=self.ask,
                  volume=1)

    def copy_rates_from_pos(self, s, tf, start, count):
        return None if not self.alive else self.rates[-count:]

    def copy_ticks_from(self, s, since, count, flags):
        return None if not self.alive else [t for t in self.ticks if t["time_msc"] / 1000 >= since.timestamp()]

    def market_book_add(self, s):
        return False

    def market_book_get(self, s):
        return None

    def positions_get(self, symbol=None, ticket=None):
        if not self.alive:
            return None
        for k in list(self._hidden):
            self._hidden[k] -= 1
            if self._hidden[k] <= 0:
                del self._hidden[k]
        ps = [p for t, p in self.pos.items() if t not in self._hidden]
        if symbol:
            ps = [p for p in ps if p.symbol == symbol]
        if ticket:
            ps = [p for p in ps if p.ticket == ticket]
        return tuple(ps)

    def orders_get(self, symbol=None):
        return None if not self.alive else tuple(o for o in self.ords.values() if not symbol or o.symbol == symbol)

    def history_deals_get(self, position=None, **k):
        return None if not self.alive else tuple(d for d in self.deals if d.position_id == position)

    def _deal(self, p, dtype, entry, price):
        self.deals.append(NS(ticket=next(self._ids), order=next(self._ids), position_id=p.ticket, symbol=p.symbol,
                             type=dtype, entry=entry, volume=p.volume, price=price, commission=-0.5, fee=0.0,
                             time_msc=int(self.now * 1000)))

    def order_send(self, req):
        if not self.alive:
            return None
        self.sent.append(dict(req))
        if self.reject is not None:
            code, self.reject = self.reject, None
            return NS(retcode=code, comment="rejeitada", deal=0, order=0, price=0.0, volume=0.0)
        a = req["action"]
        done = NS(retcode=self.TRADE_RETCODE_DONE, comment="ok", deal=0, order=next(self._ids), price=0.0, volume=0.0)
        if a == self.TRADE_ACTION_DEAL and "position" not in req:
            buy = req["type"] == self.ORDER_TYPE_BUY
            t = next(self._ids)
            self.pos[t] = NS(ticket=t, symbol=req["symbol"], type=self.POSITION_TYPE_BUY if buy else self.POSITION_TYPE_SELL,
                             volume=req["volume"], price_open=self.ask if buy else self.bid,
                             sl=0.0 if self.drop_sl else req.get("sl", 0.0), tp=req.get("tp", 0.0),
                             magic=req.get("magic", 0), comment=req.get("comment", ""), time_msc=int(self.now * 1000))
            self._deal(self.pos[t], self.DEAL_TYPE_BUY if buy else self.DEAL_TYPE_SELL, self.DEAL_ENTRY_IN, self.pos[t].price_open)
            if self.hide_fills:
                self._hidden[t] = self.hide_fills
                done.retcode = self.TRADE_RETCODE_PLACED
            return done
        if a == self.TRADE_ACTION_DEAL:
            p = self.pos.pop(req["position"])
            sell = p.type == self.POSITION_TYPE_BUY
            self._deal(p, self.DEAL_TYPE_SELL if sell else self.DEAL_TYPE_BUY, self.DEAL_ENTRY_OUT,
                       self.bid if sell else self.ask)
            return done
        if a == self.TRADE_ACTION_SLTP:
            if not self.ignore_sltp:
                self.pos[req["position"]].sl = req["sl"]
            return done
        if a == self.TRADE_ACTION_REMOVE:
            self.ords.pop(req["order"], None)
            return done
        raise AssertionError(f"ação inesperada {a}")

    # helpers de teste
    def hit(self, price_bid, price_ask=None):
        """Move o mercado e executa SL/TP como a corretora faria."""
        self.bid, self.ask = price_bid, price_ask or price_bid + 5
        for t, p in list(self.pos.items()):
            long_ = p.type == self.POSITION_TYPE_BUY
            px = self.bid if long_ else self.ask
            if (p.sl and ((px <= p.sl) if long_ else (px >= p.sl))) or (p.tp and ((px >= p.tp) if long_ else (px <= p.tp))):
                self.pos.pop(t)
                self._deal(p, self.DEAL_TYPE_SELL if long_ else self.DEAL_TYPE_BUY, self.DEAL_ENTRY_OUT, px)

    def open_foreign(self, buy=True, magic=0):
        t = next(self._ids)
        self.pos[t] = NS(ticket=t, symbol=self.symbol, type=self.POSITION_TYPE_BUY if buy else self.POSITION_TYPE_SELL,
                         volume=1.0, price_open=self.ask, sl=0.0, tp=0.0, magic=magic, comment="manual",
                         time_msc=int(self.now * 1000))
        return t
