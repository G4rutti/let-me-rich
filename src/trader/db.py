"""Schema SQLite e acesso. Só guarda dado estruturado gerado pelo nosso código ou pelo Claude."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trader.config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,                 -- live | dry
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,
    setup TEXT NOT NULL,
    status TEXT NOT NULL,               -- pending | open | closed | cancelled
    entry_list_id TEXT UNIQUE NOT NULL, -- listClientOrderId do OPOCO
    protect_list_id TEXT,               -- OCO que protege a posição agora
    entry_limit REAL NOT NULL,
    planned_qty REAL NOT NULL,
    qty REAL,
    entry_price REAL,
    initial_stop REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    created_at TEXT NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,                   -- stop | target | manual | partial_final | emergency | kill
    realized_usd REAL DEFAULT 0,        -- PnL já realizado (parciais), líquido de taxa
    fees_usd REAL DEFAULT 0,
    pnl_usd REAL,
    r_multiple REAL,
    usdt_brl REAL,                      -- cotação no fill (fiscal)
    reason TEXT,
    cycle_id TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trade_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    client_id TEXT,
    exchange_id TEXT,
    list_id TEXT,
    status TEXT,
    qty REAL,
    price REAL,
    filled REAL,
    avg_price REAL,
    fee REAL,
    fee_asset TEXT,
    usdt_brl REAL
);
CREATE TABLE IF NOT EXISTS positions_snapshot (
    ts TEXT NOT NULL, cycle_id TEXT, asset TEXT NOT NULL,
    free REAL, locked REAL, usd_value REAL
);
CREATE TABLE IF NOT EXISTS equity_history (
    ts TEXT NOT NULL, equity_usd REAL NOT NULL, usdt_brl REAL
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cycle_id TEXT,
    author TEXT NOT NULL,               -- claude | system
    kind TEXT NOT NULL,
    symbol TEXT,
    setup TEXT,
    trade_id INTEGER,
    thesis TEXT,
    outcome TEXT,
    lesson TEXT,
    data_json TEXT
);
CREATE TABLE IF NOT EXISTS shadow_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL,
    setup TEXT NOT NULL,
    status TEXT NOT NULL,               -- open | closed
    opened_at TEXT NOT NULL,
    entry_price REAL NOT NULL,
    qty REAL NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    time_exit_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_usd REAL,
    r_multiple REAL
);
CREATE TABLE IF NOT EXISTS risk_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    cycle_id TEXT,
    action TEXT NOT NULL,
    symbol TEXT,
    decision TEXT NOT NULL,             -- approved | rejected | intent | result | error
    code TEXT,
    detail_json TEXT
);
CREATE TABLE IF NOT EXISTS cycles (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,                 -- cycle | weekly | manual
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT,
    est_cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    num_turns INTEGER,
    summary_json TEXT
);
CREATE TABLE IF NOT EXISTS listings (
    symbol TEXT PRIMARY KEY,
    first_candle_ms INTEGER,
    tags TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS ix_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS ix_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS ix_shadow_status ON shadow_trades(status);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    if path is None:
        DATA_DIR.mkdir(exist_ok=True)
        path = DATA_DIR / "trader.db"
    conn = sqlite3.connect(path, isolation_level=None, timeout=30)  # autocommit
    conn.row_factory = sqlite3.Row
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def get_state(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_state(conn, key: str, value) -> None:
    conn.execute("INSERT INTO state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))


def insert(conn, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values())).lastrowid


def update(conn, table: str, row_id, fields: dict, key: str = "id") -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", (*fields.values(), row_id))
