"""Wrapper ccxt da Binance spot: regras de precisão, retries, clientOrderId, OPOCO/OCO, redação de segredos.

Único ponto específico da Binance: place_protected_entry / place_oco_sell / cancel_list / open_order_lists
(order lists não são unificadas no ccxt). Trocar de exchange = reimplementar esses quatro.
"""
import hashlib
import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import ccxt


class ExchangeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def fmt(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def client_id(*parts) -> str:
    """ID determinístico (regex Binance ^[.A-Z:/a-z0-9_-]{1,36}$): mesmo input => mesmo ID => retry não duplica."""
    return "lmr" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class MarketRules:
    symbol: str          # formato ccxt: PEPE/USDT
    id: str              # formato Binance: PEPEUSDT
    base: str
    active: bool
    tick: Decimal
    step: Decimal
    min_qty: Decimal
    market_step: Decimal
    market_min_qty: Decimal
    market_max_qty: Decimal
    min_notional: Decimal
    opo_allowed: bool
    oco_allowed: bool
    ask_mult_up: Decimal     # PERCENT_PRICE_BY_SIDE, limite de preço de venda sobre o preço médio
    bid_mult_up: Decimal     # limite de preço de compra sobre o preço médio

    def floor_qty(self, q, market: bool = False) -> Decimal:
        step = self.market_step if market and self.market_step > 0 else self.step
        return (D(q) / step).to_integral_value(ROUND_FLOOR) * step

    def floor_price(self, p) -> Decimal:
        return (D(p) / self.tick).to_integral_value(ROUND_FLOOR) * self.tick

    def ceil_price(self, p) -> Decimal:
        return (D(p) / self.tick).to_integral_value(ROUND_CEILING) * self.tick


def rules_from_info(symbol: str, info: dict) -> MarketRules:
    """Monta as regras a partir do objeto cru de exchangeInfo (fonte da verdade, sem depender do mapeamento ccxt)."""
    f = {x["filterType"]: x for x in info["filters"]}
    lot, mlot = f["LOT_SIZE"], f.get("MARKET_LOT_SIZE", {})
    pps = f.get("PERCENT_PRICE_BY_SIDE", {})
    notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
    return MarketRules(
        symbol=symbol,
        id=info["symbol"],
        base=info["baseAsset"],
        active=info["status"] == "TRADING" and info.get("isSpotTradingAllowed", True),
        tick=D(f["PRICE_FILTER"]["tickSize"]).normalize(),
        step=D(lot["stepSize"]).normalize(),
        min_qty=D(lot["minQty"]),
        market_step=D(mlot.get("stepSize", "0")).normalize(),
        market_min_qty=D(mlot.get("minQty", "0")),
        market_max_qty=D(mlot.get("maxQty", "0")),
        min_notional=D(notional.get("minNotional", "5")),
        opo_allowed=bool(info.get("opoAllowed")),
        oco_allowed=bool(info.get("ocoAllowed")),
        ask_mult_up=D(pps.get("askMultiplierUp", "5")),
        bid_mult_up=D(pps.get("bidMultiplierUp", "5")),
    )


_RETRYABLE = (ccxt.NetworkError,)          # inclui RequestTimeout e DDoSProtection/RateLimitExceeded
_RATE = (ccxt.DDoSProtection, ccxt.RateLimitExceeded)


class Exchange:
    def __init__(self, secrets: dict | None = None, client=None, sleep=time.sleep):
        secrets = secrets or {}
        self._secrets = [v for v in secrets.values() if v and len(v) >= 8]
        self._sleep = sleep
        self.client = client or ccxt.binance({
            "apiKey": secrets.get("BINANCE_API_KEY") or None,
            "secret": secrets.get("BINANCE_SECRET") or None,
            "enableRateLimit": True,
            "options": {"defaultType": "spot", "adjustForTimeDifference": True, "recvWindow": 5000,
                        "warnOnFetchOpenOrdersWithoutSymbol": False},
        })
        self.client.verbose = False
        self._rules: dict[str, MarketRules] = {}

    # ---- infraestrutura -------------------------------------------------
    def redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        return text

    def _call(self, fn, *args, retries: int = 3, **kwargs):
        for attempt in range(retries + 1):
            try:
                return fn(*args, **kwargs)
            except _RETRYABLE as e:
                if attempt == retries:
                    raise ExchangeError("NETWORK", self.redact(str(e))[:300]) from None
                # ccxt não respeita Retry-After; 429 ignorado vira ban (418), então espera longa
                self._sleep(60 if isinstance(e, _RATE) else 2 ** attempt)
            except ccxt.BaseError as e:
                msg = self.redact(str(e))[:300]
                code = "DUPLICATE" if ("-2010" in msg and "uplicate" in msg) else type(e).__name__.upper()
                raise ExchangeError(code, msg) from None

    # ---- leitura --------------------------------------------------------
    def load(self) -> None:
        if not self._rules:
            markets = self._call(self.client.load_markets)
            for sym, m in markets.items():
                if m.get("spot") and m.get("quote") == "USDT" and m.get("info", {}).get("filters"):
                    self._rules[sym] = rules_from_info(sym, m["info"])

    def rules(self, symbol: str) -> MarketRules:
        self.load()
        if symbol not in self._rules:
            raise ExchangeError("UNKNOWN_SYMBOL", symbol)
        return self._rules[symbol]

    def symbols(self) -> list[str]:
        self.load()
        return [s for s, r in self._rules.items() if r.active]

    def server_time_offset_ms(self) -> int:
        return int(self._call(self.client.fetch_time)) - int(time.time() * 1000)

    def tickers(self) -> dict:
        return self._call(self.client.fetch_tickers)

    def ticker(self, symbol: str) -> dict:
        return self._call(self.client.fetch_ticker, symbol)

    def ohlcv(self, symbol: str, timeframe: str, limit: int = 200, since: int | None = None) -> list:
        return self._call(self.client.fetch_ohlcv, symbol, timeframe, since, limit)

    def balance(self) -> dict:
        """{asset: {'free': Decimal, 'locked': Decimal}} só com saldo > 0."""
        raw = self._call(self.client.fetch_balance)
        out = {}
        for b in raw.get("info", {}).get("balances", []):
            free, locked = D(b["free"]), D(b["locked"])
            if free > 0 or locked > 0:
                out[b["asset"]] = {"free": free, "locked": locked}
        return out

    def open_orders(self, symbol: str | None = None) -> list:
        return self._call(self.client.fetch_open_orders, symbol)

    def fetch_order_by_client_id(self, symbol: str, cid: str) -> dict:
        return self._call(self.client.fetch_order, None, symbol, {"origClientOrderId": cid})

    def my_trades(self, symbol: str, since_ms: int | None = None) -> list:
        return self._call(self.client.fetch_my_trades, symbol, since_ms)

    def order_fills(self, symbol: str, order_id: str) -> dict:
        """Execuções de uma ordem: qty, quote (USDT) e taxas por ativo. A Binance só informa taxa nos trades."""
        trades = self._call(self.client.fetch_my_trades, symbol, None, None, {"orderId": order_id})
        out = {"qty": D(0), "quote": D(0), "fees": {}}
        for t in trades:
            out["qty"] += D(t["amount"])
            out["quote"] += D(t["cost"])
            fee = t.get("fee") or {}
            if fee.get("cost"):
                out["fees"][fee["currency"]] = out["fees"].get(fee["currency"], D(0)) + D(fee["cost"])
        return out

    def api_restrictions(self) -> dict:
        """Permissões da chave: enableWithdrawals, enableSpotAndMarginTrading, ipRestrict, ..."""
        return self._call(self.client.sapi_get_account_apirestrictions)

    def open_order_lists(self) -> list:
        return self._call(self.client.private_get_openorderlist)

    def order_list(self, list_client_id: str) -> dict:
        return self._call(self.client.private_get_orderlist, {"origClientOrderId": list_client_id})

    # ---- escrita (chamada SÓ depois do risk manager) --------------------
    def place_protected_entry(self, symbol: str, qty: Decimal, limit: Decimal, stop: Decimal,
                              target: Decimal, list_id: str) -> dict:
        """OPOCO: compra LIMIT + OCO de venda (alvo LIMIT_MAKER, stop STOP_LOSS a mercado) que entra sozinho no fill,
        com a quantidade realmente recebida (já descontada a taxa)."""
        r = self.rules(symbol)
        params = {
            "symbol": r.id,
            "listClientOrderId": list_id,
            "workingType": "LIMIT", "workingSide": "BUY", "workingTimeInForce": "GTC",
            "workingPrice": fmt(limit), "workingQuantity": fmt(qty),
            "workingClientOrderId": list_id + "-w",
            "pendingSide": "SELL",
            "pendingAboveType": "LIMIT_MAKER", "pendingAbovePrice": fmt(target),
            "pendingAboveClientOrderId": list_id + "-t",
            "pendingBelowType": "STOP_LOSS", "pendingBelowStopPrice": fmt(stop),
            "pendingBelowClientOrderId": list_id + "-s",
        }
        return self._idempotent(self.client.private_post_orderlist_opoco, params, list_id)

    def place_oco_sell(self, symbol: str, qty: Decimal, stop: Decimal, target: Decimal, list_id: str) -> dict:
        r = self.rules(symbol)
        params = {
            "symbol": r.id, "side": "SELL", "quantity": fmt(qty),
            "listClientOrderId": list_id,
            "aboveType": "LIMIT_MAKER", "abovePrice": fmt(target), "aboveClientOrderId": list_id + "-t",
            "belowType": "STOP_LOSS", "belowStopPrice": fmt(stop), "belowClientOrderId": list_id + "-s",
        }
        return self._idempotent(self.client.private_post_orderlist_oco, params, list_id)

    def cancel_list(self, symbol: str, list_id: str) -> dict:
        return self._call(self.client.private_delete_orderlist,
                          {"symbol": self.rules(symbol).id, "listClientOrderId": list_id}, retries=1)

    def market_sell(self, symbol: str, qty: Decimal, cid: str) -> dict:
        try:
            return self._call(self.client.create_order, symbol, "market", "sell", float(qty), None,
                              {"clientOrderId": cid})
        except ExchangeError as e:
            if e.code == "DUPLICATE":
                return self.fetch_order_by_client_id(symbol, cid)
            raise

    def cancel_all(self, symbol: str) -> None:
        try:
            self._call(self.client.cancel_all_orders, symbol, retries=1)
        except ExchangeError as e:
            if "-2011" not in str(e):   # "Unknown order sent" = nada para cancelar
                raise

    def _idempotent(self, fn, params: dict, list_id: str) -> dict:
        try:
            return self._call(fn, params)
        except ExchangeError as e:
            if e.code == "DUPLICATE":   # já foi aceita numa tentativa anterior
                return self.order_list(list_id)
            raise
