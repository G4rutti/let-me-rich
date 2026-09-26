"""Wrapper chamado pelo Agendador de Tarefas.

`uv run python -m trader.run_cycle`            ciclo normal
`uv run python -m trader.run_cycle --weekly`   revisão semanal (só leitura + propostas)
`... --model sonnet`                           sobrescreve o modelo (testes)

Garante: um ciclo por vez (lock), Claude sem acesso a nada além do MCP, log + custo estimado por ciclo,
e SEMPRE um sync em Python no final (nenhuma posição fica sem stop mesmo se o Claude falhar).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from trader import shadow
from trader.config import CONFIG_DIR, DATA_DIR, ROOT, load_config, load_secrets
from trader.db import connect, get_state, insert, now_iso, update
from trader.exchange import Exchange, ExchangeError
from trader.lock import exclusive
from trader.notify import notify
from trader.regime import get_regime
from trader.scan import scan
from trader.sync import sync
from trader.trading import Ctx, TradeError

PROMPT = {
    "cycle": "Execute UM ciclo completo de trading seguindo o CLAUDE.md, na ordem. Termine com a saída no schema.",
    "weekly": ("Revisão semanal. Use as tools de leitura (get_setup_stats, get_recent_journal com n=50, "
               "get_portfolio, get_safety_status) para avaliar a semana: o que funcionou, o que não, agente vs sombra. "
               "Se houver mudança de estratégia ou de limites que valha propor, use write_proposal (uma por tema, "
               "com evidência numérica). Você NÃO opera nesta execução. Termine com a saída no schema."),
}

ACTION = {"type": "object", "additionalProperties": False, "required": ["type", "symbol", "detail"], "properties": {
    "type": {"enum": ["entry", "skip", "move_stop", "partial", "close", "hold", "rejected"]},
    "symbol": {"type": "string"}, "detail": {"type": "string", "maxLength": 300}}}
SCHEMA = {
    "cycle": {"type": "object", "additionalProperties": False,
              "required": ["preflight_status", "regime", "actions", "postmortems_written", "summary"],
              "properties": {"preflight_status": {"enum": ["OK", "ABORT", "MANAGE_ONLY"]},
                             "regime": {"type": "string"}, "actions": {"type": "array", "items": ACTION},
                             "postmortems_written": {"type": "integer"},
                             "summary": {"type": "string", "maxLength": 600}}},
    "weekly": {"type": "object", "additionalProperties": False, "required": ["proposals", "summary"],
               "properties": {"proposals": {"type": "array", "items": {"type": "string"}},
                              "summary": {"type": "string", "maxLength": 2000}}},
}


def claude_path(cfg: dict) -> str:
    p = cfg.get("claude_path") or shutil.which("claude") or str(Path.home() / ".local/bin/claude.exe")
    if not Path(p).exists() and not shutil.which(p):
        raise SystemExit(f"claude não encontrado ({p}); configure claude_path em config/cycle.yaml")
    return p


def build_cmd(kind: str, cc: dict, model: str | None) -> list[str]:
    opts = cc["weekly"] if kind == "weekly" else cc
    return [
        claude_path(cc), "-p", PROMPT[kind],
        "--model", model or opts["model"], "--effort", opts["effort"],
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--settings", str(ROOT / ".claude" / "cycle-settings.json"),
        "--mcp-config", str(ROOT / ".mcp.json"), "--strict-mcp-config",
        "--tools", "Agent",
        "--allowedTools", "mcp__trader__*", "Agent",
        "--disallowedTools", "Bash", "PowerShell", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch",
        "Read", "Glob", "Grep",
        "--output-format", "json", "--json-schema", json.dumps(SCHEMA[kind]),
        "--max-turns", str(opts["max_turns"]), "--max-budget-usd", str(cc["max_budget_usd"]),
        "--no-session-persistence",
    ]


def run_claude(kind: str, cycle_id: str, cc: dict, model: str | None) -> tuple[dict, str]:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}   # em -p ela passaria na frente da assinatura
    env.update(TRADER_CYCLE_ID=cycle_id, TRADER_CYCLE_KIND=kind, DISABLE_AUTOUPDATER="1")
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    try:
        p = subprocess.run(build_cmd(kind, cc, model), cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=cc["timeout_min"] * 60)
        out, err = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out, err = (e.stdout or ""), f"TIMEOUT após {cc['timeout_min']} min"
        out = out.decode() if isinstance(out, bytes) else out
    (logs / f"{cycle_id}.json").write_text(out or "", encoding="utf-8")
    if err:
        (logs / f"{cycle_id}.err").write_text(err, encoding="utf-8")
    try:
        return json.loads(out), err
    except (json.JSONDecodeError, TypeError):
        return {}, err or "saída não é JSON"


def classify(result: dict, err: str, preflight_ran: bool) -> str:
    if not result:
        return "error"
    if result.get("is_error") or result.get("subtype") not in ("success", None):
        return "error"
    if not isinstance(result.get("structured_output"), dict):
        return "error"
    if not preflight_ran:
        return "error_no_mcp"   # o Claude respondeu sem chamar o MCP: servidor não conectou
    return "ok"


def post_cycle(ctx: Ctx, kind: str, cycle_id: str) -> dict:
    """Rede de segurança em Python + sombra. Roda mesmo se o Claude falhou."""
    out = {}
    try:
        out["sync_events"] = sync(ctx)["events"]
    except (ExchangeError, TradeError) as e:
        out["sync_error"] = str(e)
    if kind == "cycle":
        try:
            last = get_state(ctx.conn, "last_scan") or {}
            cands = last.get("candidates") if last.get("cycle_id") == cycle_id else scan(ctx.ex, ctx.conn, ctx.cfg)["candidates"]
            out["shadow"] = shadow.step(ctx.conn, ctx.ex, ctx.cfg, cands, get_regime(ctx.ex)["regime"])
        except (ExchangeError, TradeError) as e:
            out["shadow_error"] = str(e)
    return out


def main(argv: list[str]) -> int:
    kind = "weekly" if "--weekly" in argv else "cycle"
    model = argv[argv.index("--model") + 1] if "--model" in argv else None
    cc = yaml.safe_load((CONFIG_DIR / "cycle.yaml").read_text(encoding="utf-8"))
    cycle_id = f"{kind}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    secrets = load_secrets()
    try:
        with exclusive("cycle"):
            conn = connect()
            ctx = Ctx(conn, Exchange(secrets), load_config(), cycle_id=cycle_id, notify=lambda m: notify(m, secrets))
            insert(conn, "cycles", {"id": cycle_id, "kind": kind, "started_at": now_iso(), "status": "running"})
            t0 = time.time()
            result, err = run_claude(kind, cycle_id, cc, model)
            status = classify(result, err, get_state(conn, "last_preflight") == cycle_id or kind == "weekly")
            so = result.get("structured_output") or {}
            if status == "ok" and so.get("preflight_status") == "ABORT":
                status = "abort"
            usage = result.get("usage") or {}
            post = post_cycle(ctx, kind, cycle_id)
            update(conn, "cycles", cycle_id, {
                "ended_at": now_iso(), "status": status, "est_cost_usd": result.get("total_cost_usd"),
                "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                "num_turns": result.get("num_turns"),
                "summary_json": json.dumps({"out": so, "post": post, "model_usage": result.get("modelUsage"),
                                            "secs": round(time.time() - t0)}, default=str)[:20000]})
            if status.startswith("error"):
                hint = (err or result.get("result") or "")[-400:]
                notify(f"❗ ciclo {cycle_id} falhou ({status}). Limite de uso da assinatura? Veja data/logs.\n{hint}",
                       secrets)
            elif kind == "weekly":
                notify(f"📋 revisão semanal: {len(so.get('proposals', []))} proposta(s) em proposals/\n"
                       f"{so.get('summary', '')[:1500]}", secrets)
            print(json.dumps({"cycle": cycle_id, "status": status, "structured_output": so, "post": post},
                             ensure_ascii=False, default=str, indent=1))
            return 0 if not status.startswith("error") else 1
    except BlockingIOError:
        print("outro ciclo em andamento; saindo")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
