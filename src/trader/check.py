"""Checagem SOMENTE LEITURA da conexão: `uv run python -m trader.check`. Não envia ordem."""
from trader.config import load_secrets
from trader.exchange import Exchange


def main() -> None:
    secrets = load_secrets()
    ex = Exchange(secrets)
    ex.load()
    print(f"mercados USDT spot ativos: {len(ex.symbols())}")
    print(f"diferença de relógio: {ex.server_time_offset_ms()} ms")
    for s in ("BTC/USDT", "PEPE/USDT"):
        r = ex.rules(s)
        print(f"{s}: tick={r.tick} step={r.step} minNotional={r.min_notional} opo={r.opo_allowed} oco={r.oco_allowed}")
    if not secrets["BINANCE_API_KEY"]:
        print("sem chave em config/.env — pulando checagens privadas")
        return
    rs = ex.api_restrictions()
    print("permissões da chave:", {k: rs.get(k) for k in (
        "enableSpotAndMarginTrading", "enableWithdrawals", "enableInternalTransfer",
        "enableMargin", "enableFutures", "permitsUniversalTransfer", "ipRestrict")})
    bal = ex.balance()
    print("saldos:", {a: f"{v['free']} livre / {v['locked']} travado" for a, v in bal.items()})


if __name__ == "__main__":
    main()
