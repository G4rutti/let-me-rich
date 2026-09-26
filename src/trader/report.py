"""Relatório agente vs sombra e export CSV fiscal.

`uv run python -m trader.report`            -> resumo
`uv run python -m trader.report --csv f.csv` -> todas as ordens executadas (para o imposto)
"""
import csv
import sys

from trader.db import connect


def summary(conn, table: str, since: str | None = None) -> dict:
    q = f"SELECT pnl_usd, r_multiple FROM {table} WHERE status='closed' AND pnl_usd IS NOT NULL"
    args = ()
    if since:
        q += " AND closed_at >= ?"
        args = (since,)
    rows = conn.execute(q + " ORDER BY closed_at", args).fetchall()
    n = len(rows)
    if not n:
        return {"trades": 0}
    pnl = [r["pnl_usd"] for r in rows]
    rs = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    peak = cum = dd = 0.0
    for p in pnl:
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return {"trades": n, "pnl_usd": round(sum(pnl), 2), "win_rate": round(sum(p > 0 for p in pnl) / n, 3),
            "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None, "max_drawdown_usd": round(dd, 2)}


def compare(conn, since: str | None = None) -> dict:
    return {"agente": summary(conn, "trades", since), "sombra": summary(conn, "shadow_trades", since)}


def export_csv(conn, path: str) -> int:
    rows = conn.execute("""
        SELECT o.ts AS data_utc, o.symbol AS par, o.side AS lado, o.type AS tipo, o.qty AS quantidade,
               o.avg_price AS preco_usdt, o.qty * o.avg_price AS total_usdt, o.fee AS taxa, o.fee_asset AS ativo_taxa,
               o.usdt_brl AS cotacao_usdt_brl, (o.qty * o.avg_price * o.usdt_brl) AS total_brl,
               o.trade_id, o.client_id, o.exchange_id
        FROM orders o WHERE o.status='FILLED' ORDER BY o.ts""").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(rows[0].keys() if rows else ["sem dados"])
        w.writerows([tuple(r) for r in rows])
    return len(rows)


if __name__ == "__main__":
    conn = connect()
    if "--csv" in sys.argv:
        path = sys.argv[sys.argv.index("--csv") + 1]
        print(f"{export_csv(conn, path)} ordens exportadas para {path}")
    else:
        import json
        print(json.dumps(compare(conn), indent=2, ensure_ascii=False))
