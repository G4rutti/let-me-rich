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
    horizon TEXT NOT NULL,              -- intraday | swing
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
    exit_reason TEXT,                   -- stop | target | manual | emergency | kill | orphan
    risk_usd REAL,                      -- risco inicial (para R múltiplo)
    cost_usd REAL,                      -- USDT gasto na compra (+ taxa em USDT)
    proceeds_usd REAL DEFAULT 0,        -- USDT recebido nas vendas (parciais + final), líquido
    fees_usd REAL DEFAULT 0,            -- taxas pagas em outro ativo (BNB), em USD
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
-- ---- modo B3 (WIN via MT5) ----
CREATE TABLE IF NOT EXISTS b3_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant TEXT NOT NULL,              -- real | sombra_regra | sombra_sem_macro
    mode TEXT NOT NULL,                 -- live | dry (dry e sombras = papel)
    day TEXT NOT NULL,                  -- pregão (data de Brasília)
    symbol TEXT NOT NULL,
    setup TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    side TEXT NOT NULL,                 -- long | short
    status TEXT NOT NULL,               -- pending | open | closed | cancelled
    contracts INTEGER NOT NULL,
    comment TEXT,                       -- vai na ordem do MT5 (idempotência/reconciliação)
    position_ticket INTEGER,
    signal_price REAL NOT NULL,         -- bid/ask no momento do sinal
    entry_price REAL,
    initial_sl REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    risk_brl REAL NOT NULL,             -- perda planejada no stop, custos incluídos (= 1R)
    slippage_points REAL,               -- positivo = pior que o sinal
    created_at TEXT NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,                   -- stop | target | breakeven | invalidation | flatten | manual | watchdog | kill
    pnl_brl REAL,
    r_multiple REAL,
    plan_version INTEGER,
    bias TEXT,
    risk_level TEXT,
    regime TEXT,
    context_json TEXT                   -- leitura dos analistas, nível do gatilho etc.
);
CREATE TABLE IF NOT EXISTS b3_bars (
    symbol TEXT NOT NULL, tf TEXT NOT NULL, time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, tf, time)
);
CREATE TABLE IF NOT EXISTS b3_ticks (
    symbol TEXT NOT NULL, time TEXT NOT NULL, bid REAL, ask REAL, last REAL, volume REAL, aggressor TEXT
);
CREATE TABLE IF NOT EXISTS b3_book (symbol TEXT NOT NULL, time TEXT NOT NULL, book_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS b3_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,                 -- plan | revise
    created_at TEXT NOT NULL,
    cycle_id TEXT,
    plan_json TEXT NOT NULL,
    UNIQUE (day, version)
);
CREATE TABLE IF NOT EXISTS b3_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    variant TEXT NOT NULL,
    setup_id TEXT NOT NULL,
    bar_time TEXT NOT NULL,
    side TEXT NOT NULL,
    decision TEXT NOT NULL,             -- approved | rejected | error
    code TEXT,
    detail_json TEXT,
    UNIQUE (variant, setup_id, bar_time)
);
CREATE TABLE IF NOT EXISTS b3_dossiers (day TEXT PRIMARY KEY, created_at TEXT NOT NULL, dossier_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_b3_trades_day ON b3_trades(day, variant);
CREATE INDEX IF NOT EXISTS ix_b3_ticks ON b3_ticks(symbol, time);
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
    # check_same_thread=False: o MCP roda tools em threads, mas serializa tudo com um lock global
    conn = sqlite3.connect(path, isolation_level=None, timeout=30, check_same_thread=False)  # autocommit
    conn.row_factory = sqlite3.Row
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if "market" not in {r["name"] for r in conn.execute("PRAGMA table_info(journal)")}:
        conn.execute("ALTER TABLE journal ADD COLUMN market TEXT NOT NULL DEFAULT 'crypto'")   # crypto | b3
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
