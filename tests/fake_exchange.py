"""Exchange falsa com a mesma interface de trader.exchange.Exchange (só o que o bot usa)."""
import itertools
from decimal import Decimal as Dec

from trader.exchange import ExchangeError


class FakeExchange:
    def __init__(self, rules: dict, prices: dict, balances: dict | None = None):
        self._rules = rules
        self.prices = {k: Dec(str(v)) for k, v in prices.items()}
        self.bal = {a: {"free": Dec(str(v)), "locked": Dec(0)} for a, v in (balances or {"USDT": 90}).items()}
        self.orders = {}        # client_id -> order
        self.fills = {}         # order_id -> fills
        self.calls = []
        self._ids = itertools.count(1)
        self.fail_oco = 0       # quantas próximas chamadas de OCO devem falhar

    # leitura
    def rules(self, s):
        if s not in self._rules:
            raise ExchangeError("UNKNOWN_SYMBOL", s)
        return self._rules[s]

    def symbols(self):
        return list(self._rules)

    def ticker(self, s):
        if s not in self.prices:
            raise ExchangeError("BADSYMBOL", s)
        p = float(self.prices[s])
        return {"last": p, "bid": p * 0.9995, "ask": p * 1.0005}

    def ohlcv(self, s, tf, limit=200, since=None):
        p = float(self.prices.get(s, 1))
        return [[i * 3_600_000, p, p * 1.01, p * 0.99, p, 100.0] for i in range(limit)]

    def balance(self):
        return {a: dict(v) for a, v in self.bal.items() if v["free"] > 0 or v["locked"] > 0}

    def server_time_offset_ms(self):
        return 10

    def api_restrictions(self):
        return {"enableSpotAndMarginTrading": True, "enableWithdrawals": False, "ipRestrict": True}

    def fetch_order_by_client_id(self, s, cid):
        if cid not in self.orders:
            raise ExchangeError("ORDERNOTFOUND", cid)
        return self.orders[cid]

    def order_fills(self, s, oid):
        return self.fills.get(oid, {"qty": Dec(0), "quote": Dec(0), "fees": {}})

    # helpers de teste
    def _order(self, cid, status, filled=0, orig=0):
        o = {"id": str(next(self._ids)), "clientOrderId": cid, "status": status.lower(), "filled": filled,
             "info": {"status": status, "origQty": str(orig)}}
        self.orders[cid] = o
        return o

    def fill(self, cid, qty, price, fees=None, status="FILLED"):
        o = self.orders[cid]
        o["info"]["status"] = status
        o["filled"] = float(qty)
        self.fills[o["id"]] = {"qty": Dec(str(qty)), "quote": Dec(str(qty)) * Dec(str(price)),
                               "fees": {k: Dec(str(v)) for k, v in (fees or {}).items()}}

    # escrita
    def place_protected_entry(self, s, qty, limit, stop, target, lid):
        self.calls.append(("opoco", s, qty, limit, stop, target, lid))
        self._order(lid + "-w", "NEW", orig=qty)
        self._order(lid + "-t", "PENDING_NEW")
        self._order(lid + "-s", "PENDING_NEW")
        return {"listClientOrderId": lid}

    def place_oco_sell(self, s, qty, stop, target, lid):
        self.calls.append(("oco", s, qty, stop, target, lid))
        if self.fail_oco:
            self.fail_oco -= 1
            raise ExchangeError("INVALIDORDER", "oco falhou")
        self._order(lid + "-t", "NEW", orig=qty)
        self._order(lid + "-s", "NEW", orig=qty)
        base = s.split("/")[0]
        self.bal[base]["free"] -= qty
        self.bal[base]["locked"] += qty
        return {"listClientOrderId": lid}

    def cancel_list(self, s, lid):
        self.calls.append(("cancel_list", s, lid))
        found = False
        for leg in ("-t", "-s", "-w"):
            o = self.orders.get(lid + leg)
            if o and o["info"]["status"] in ("NEW", "PENDING_NEW", "PARTIALLY_FILLED"):
                o["info"]["status"] = "CANCELED"
                found = True
        if not found:
            raise ExchangeError("ORDERNOTFOUND", "-2011 Unknown order sent.")
        base = s.split("/")[0]
        if base in self.bal:
            self.bal[base]["free"] += self.bal[base]["locked"]
            self.bal[base]["locked"] = Dec(0)
        return {}

    def cancel_all(self, s):
        self.calls.append(("cancel_all", s))
        base = s.split("/")[0]
        if base in self.bal:
            self.bal[base]["free"] += self.bal[base]["locked"]
            self.bal[base]["locked"] = Dec(0)

    def market_sell(self, s, qty, cid):
        self.calls.append(("market_sell", s, qty, cid))
        o = self._order(cid, "FILLED", filled=float(qty), orig=qty)
        price = self.prices[s]
        self.fills[o["id"]] = {"qty": qty, "quote": qty * price, "fees": {"USDT": qty * price * Dec("0.001")}}
        base = s.split("/")[0]
        self.bal[base]["free"] -= qty
        self.bal.setdefault("USDT", {"free": Dec(0), "locked": Dec(0)})["free"] += qty * price
        return o

    def open_orders(self, symbol=None):
        return []   # nos testes, os símbolos com ordens vêm dos trades ativos
