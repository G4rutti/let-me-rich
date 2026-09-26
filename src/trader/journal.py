"""Diário estruturado, audit log append-only e estatística por setup.

Memory injection (arXiv 2503.16248): o diário só aceita campos tipados e texto curto sanitizado,
e é devolvido ao Claude como DADO (JSON com autor), nunca como instrução.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from trader.config import DATA_DIR, valid_symbol
from trader.db import insert, now_iso

SETUP_RE = re.compile(r"^[a-z0-9_]{3,40}$")
KINDS = ("entry", "skip", "manage", "postmortem", "cycle_note")
MAX_TEXT = 300
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁠-⁯]")


def clean_text(s, limit: int = MAX_TEXT) -> str | None:
    if s is None:
        return None
    s = _CTRL.sub(" ", str(s)).strip()
    return s[:limit]


def audit(conn, cycle_id, action: str, symbol, decision: str, code=None, detail=None, path=None) -> None:
    """Grava no SQLite e no JSONL append-only (fsync antes de retornar: intent fica registrada antes da ordem)."""
    ts = now_iso()
    detail_json = json.dumps(detail or {}, default=str)
    insert(conn, "risk_audit", {"ts": ts, "cycle_id": cycle_id, "action": action, "symbol": symbol,
                                "decision": decision, "code": code, "detail_json": detail_json})
    path = path or DATA_DIR / "audit" / f"{ts[:7]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": ts, "cycle_id": cycle_id, "action": action, "symbol": symbol,
                       "decision": decision, "code": code, "detail": detail or {}}, default=str)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def orphan_intents(conn, since_hours: int = 48) -> list[dict]:
    """Intents de ordem sem resultado registrado (processo morreu no meio): o preflight mostra."""
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat(timespec="seconds")
    rows = conn.execute("""
        SELECT i.ts, i.action, i.symbol, json_extract(i.detail_json, '$.client_id') cid FROM risk_audit i
        WHERE i.decision='intent' AND i.ts >= ? AND NOT EXISTS (
            SELECT 1 FROM risk_audit r WHERE r.decision IN ('result','error')
            AND json_extract(r.detail_json, '$.client_id') = json_extract(i.detail_json, '$.client_id'))
    """, (since,)).fetchall()
    return [dict(r) for r in rows]


def write_journal(conn, cycle_id, entry: dict, author: str = "claude") -> int:
    kind = entry.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind deve ser um de {KINDS}")
    symbol, setup = entry.get("symbol"), entry.get("setup")
    if symbol is not None and not valid_symbol(symbol):
        raise ValueError("symbol inválido")
    if setup is not None and not SETUP_RE.fullmatch(setup):
        raise ValueError("setup deve casar ^[a-z0-9_]{3,40}$")
    trade_id = entry.get("trade_id")
    if trade_id is not None and not isinstance(trade_id, int):
        raise ValueError("trade_id deve ser inteiro")
    return insert(conn, "journal", {
        "ts": now_iso(), "cycle_id": cycle_id, "author": author, "kind": kind, "symbol": symbol,
        "setup": setup, "trade_id": trade_id, "thesis": clean_text(entry.get("thesis")),
        "outcome": clean_text(entry.get("outcome")), "lesson": clean_text(entry.get("lesson")),
        "data_json": json.dumps(entry.get("data") or {}, default=str)[:2000],
    })


def recent_journal(conn, n: int = 20) -> list[dict]:
    rows = conn.execute("SELECT id, ts, author, kind, symbol, setup, trade_id, thesis, outcome, lesson "
                        "FROM journal ORDER BY id DESC LIMIT ?", (min(n, 50),)).fetchall()
    return [dict(r) for r in rows]


def trades_pending_postmortem(conn) -> list[dict]:
    rows = conn.execute("""
        SELECT id, symbol, setup, horizon, entry_price, initial_stop, target_price, exit_price, exit_reason,
               pnl_usd, r_multiple, opened_at, closed_at, reason AS entry_reason
        FROM trades t WHERE status='closed' AND NOT EXISTS (
            SELECT 1 FROM journal j WHERE j.kind='postmortem' AND j.trade_id=t.id)
        ORDER BY closed_at""").fetchall()
    return [dict(r) for r in rows]


def setup_stats(conn, cfg_stats: dict, setup: str | None = None, table: str = "trades") -> dict:
    now = datetime.now(timezone.utc)
    q = f"SELECT setup, closed_at, pnl_usd, r_multiple FROM {table} WHERE status='closed' AND r_multiple IS NOT NULL"
    args = ()
    if setup:
        q += " AND setup=?"
        args = (setup,)
    by = {}
    for r in conn.execute(q, args):
        by.setdefault(r["setup"], []).append(r)
    out = {}
    for name, rows in by.items():
        wins = {}
        for label, days in (("7d", 7), ("30d", 30), ("total", None)):
            sel = [r for r in rows if days is None or datetime.fromisoformat(r["closed_at"]) >= now - timedelta(days=days)]
            n = len(sel)
            wins[label] = {
                "n": n,
                "win_rate": round(sum(r["pnl_usd"] > 0 for r in sel) / n, 3) if n else None,
                "expectancy_r": round(sum(r["r_multiple"] for r in sel) / n, 3) if n else None,
                "pnl_usd": round(sum(r["pnl_usd"] for r in sel), 2),
            }
        out[name] = {**wins, "status": setup_status(wins["total"], cfg_stats)}
    return out


def setup_status(total: dict, c: dict) -> str:
    if total["n"] < c["min_samples"]:
        return "NEUTRO"   # amostra insuficiente
    if total["expectancy_r"] >= c["seek_expectancy_r"]:
        return "PROCURAR"
    if total["expectancy_r"] <= c["avoid_expectancy_r"]:
        return "EVITAR"
    return "NEUTRO"
