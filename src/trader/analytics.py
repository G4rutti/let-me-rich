"""Analytics do modo B3: expectativa em R e R$ (líquida de custos) por setup, horário, dia da semana, regime,
risk_level, bias e concordância com cada analista; comparação real x sombras (ablação).

`uv run python -m trader.analytics [--days 7]`   relatório (o mesmo que a revisão semanal lê)
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from trader.journal import setup_status as _status

STATUS_CFG = {"min_samples": 10, "seek_expectancy_r": 0.2, "avoid_expectancy_r": -0.1}   # mesmos cortes do cripto
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
ABLATION_MIN_TRADES = 30
VIEW_SIDE = {"positivo": "long", "negativo": "short", "long": "long", "short": "short", "compradora": "long",
             "vendedora": "short", "alta": "long", "baixa": "short"}


def closed(conn, variant: str = "real", since: str | None = None, mode: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM b3_trades WHERE status='closed' AND r_multiple IS NOT NULL AND variant=?", [variant]
    if since:
        q += " AND closed_at>=?"
        args.append(since)
    if mode:
        q += " AND mode=?"
        args.append(mode)
    return [dict(r) for r in conn.execute(q + " ORDER BY closed_at", args)]


def stats(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    pnl = [r["pnl_brl"] for r in rows]
    slip = [r["slippage_points"] for r in rows if r["slippage_points"] is not None]
    peak = cum = dd = 0.0
    for p in pnl:
        cum += p
        peak, dd = max(peak, cum), min(dd, cum - peak)
    return {"n": n, "win_rate": round(sum(p > 0 for p in pnl) / n, 3),
            "expectancy_r": round(sum(r["r_multiple"] for r in rows) / n, 3),
            "expectancy_brl": round(sum(pnl) / n, 2), "pnl_brl": round(sum(pnl), 2),
            "max_drawdown_brl": round(dd, 2), "avg_slippage_points": round(sum(slip) / len(slip), 1) if slip else None}


def _key(r: dict, by: str):
    ctx = json.loads(r.get("context_json") or "{}")
    if by in ("setup", "risk_level", "bias", "side"):
        return r[by]
    if by == "regime":
        return r.get("regime") or ctx.get("regime")
    opened = datetime.fromisoformat(r["opened_at"] or r["created_at"]).astimezone(timezone(timedelta(hours=-3)))
    if by == "hour":
        return f"{opened.hour:02d}h"
    if by == "weekday":
        return WEEKDAYS[opened.weekday()]
    if by.startswith("agree_"):
        view = (ctx.get("analysts") or {}).get(by[6:])
        side = VIEW_SIDE.get(view)
        return "sem_leitura" if side is None else ("concorda" if side == r["side"] else "discorda")
    raise ValueError(by)


def cut(rows: list[dict], by: str) -> dict:
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(_key(r, by)), []).append(r)
    return {k: stats(v) for k, v in sorted(groups.items())}


def setup_table(conn, since: str | None = None) -> dict:
    out = {}
    for name, s in cut(closed(conn, since=since), "setup").items():
        out[name] = {**s, "status": _status({"n": s["n"], "expectancy_r": s.get("expectancy_r")}, STATUS_CFG)}
    return out


def setup_status(ctx, setup: str) -> str:
    """PROCURAR | NEUTRO | EVITAR do setup na variante do contexto (EVITAR é recusado pelo risk_b3)."""
    rows = [r for r in closed(ctx.conn, variant=ctx.variant) if r["setup"] == setup]
    s = stats(rows)
    return _status({"n": s["n"], "expectancy_r": s.get("expectancy_r")}, STATUS_CFG)


def ablation(conn, since: str | None = None) -> dict:
    """real x sombras. Componente que não melhora após ~30 trades vira candidato a desligar (proposta, nunca automático)."""
    v = {name: stats(closed(conn, variant=name, since=since)) for name in ("real", "sombra_regra", "sombra_sem_macro")}
    notes = []
    real, regra, sem_macro = v["real"], v["sombra_regra"], v["sombra_sem_macro"]
    if real["n"] >= ABLATION_MIN_TRADES and regra["n"] >= ABLATION_MIN_TRADES \
            and real["expectancy_r"] <= regra["expectancy_r"]:
        notes.append("o operador (LLM) não supera a regra fixa após 30+ trades: candidato a desligar o LLM")
    if real["n"] >= ABLATION_MIN_TRADES and sem_macro["n"] >= ABLATION_MIN_TRADES \
            and real["expectancy_r"] <= sem_macro["expectancy_r"]:
        notes.append("o filtro macro (risk_level) não melhora o resultado após 30+ trades: candidato a desligar")
    return {**v, "notes": notes, "min_trades": ABLATION_MIN_TRADES}


def report(conn, days: int | None = 7) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds") if days else None
    rows = closed(conn, since=since)
    return {"period_days": days, "real": stats(rows), "ablation": ablation(conn, since),
            "by": {b: cut(rows, b) for b in ("setup", "hour", "weekday", "regime", "risk_level", "bias",
                                              "agree_macro", "agree_context", "agree_flow", "agree_bull", "agree_bear")},
            "signals_rejected": {r["code"]: r["n"] for r in conn.execute(
                "SELECT code, COUNT(*) n FROM b3_signals WHERE variant='real' AND decision='rejected' "
                + ("AND ts>=? " if since else "") + "GROUP BY code ORDER BY n DESC", (since,) if since else ())}}


def day_summary(conn, day: str) -> str:
    rows = [dict(r) for r in conn.execute(
        "SELECT variant, COUNT(*) n, COALESCE(SUM(pnl_brl),0) pnl FROM b3_trades WHERE day=? AND status='closed' "
        "GROUP BY variant", (day,))]
    if not rows:
        return f"B3 {day}: nenhum trade (real nem sombras)"
    return f"B3 {day}: " + " | ".join(f"{r['variant']}: {r['n']} trade(s) R${r['pnl']:.2f}" for r in rows)


if __name__ == "__main__":
    from trader.db import connect
    d = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    print(json.dumps(report(connect(), d), indent=1, ensure_ascii=False, default=str))
