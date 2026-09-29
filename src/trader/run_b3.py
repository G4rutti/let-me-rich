"""Roda o operador do modo B3 (codex, só tools do MCP B3). Mesmo isolamento do ciclo cripto.

`uv run python -m trader.run_b3 --kind plan`     plano do dia (antes de plan_deadline)
`uv run python -m trader.run_b3 --kind revise`   revisão curta durante o pregão (só reduz risco)
`uv run python -m trader.run_b3 --kind close`    pós-fechamento: post-mortems + nota do dia
`uv run python -m trader.run_b3 --kind weekly`   revisão semanal: analytics + propostas (nunca aplica)
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

from trader.codex import clean_env, cycle_cfg
from trader.config import DATA_DIR, ROOT
from trader.db import connect, get_state, insert, now_iso, update
from trader.lock import exclusive
from trader.notify import notify
from trader.run_cycle import build_codex_cmd, classify, parse_codex

KINDS = ("plan", "revise", "close", "weekly")
PROMPT = {
    "plan": "Execute o PLANO DO DIA do modo B3 seguindo as instruções, na ordem. Termine com a saída no schema.",
    "revise": "Execute uma REVISÃO CURTA do plano do dia do modo B3 seguindo as instruções. Termine com a saída no schema.",
    "close": "Execute o PÓS-FECHAMENTO do modo B3 (post-mortems e nota do dia). Termine com a saída no schema.",
    "weekly": "Execute a REVISÃO SEMANAL do modo B3 (analytics, real x sombras, propostas). Termine com a saída no schema.",
}
_ST = {"enum": ["OK", "ABORT", "MANAGE_ONLY"]}
_SUM = {"type": "string", "maxLength": 1500}
SCHEMA = {
    "plan": {"type": "object", "additionalProperties": False, "required": ["preflight_status", "plan_written", "summary"],
             "properties": {"preflight_status": _ST, "plan_written": {"type": "boolean"}, "summary": _SUM}},
    "revise": {"type": "object", "additionalProperties": False, "required": ["preflight_status", "revised", "summary"],
               "properties": {"preflight_status": _ST, "revised": {"type": "boolean"}, "summary": _SUM}},
    "close": {"type": "object", "additionalProperties": False,
              "required": ["postmortems_written", "day_note_written", "summary"],
              "properties": {"postmortems_written": {"type": "integer"}, "day_note_written": {"type": "boolean"},
                             "summary": _SUM}},
    "weekly": {"type": "object", "additionalProperties": False, "required": ["proposals", "summary"],
               "properties": {"proposals": {"type": "array", "items": {"type": "string"}}, "summary": _SUM}},
}

CODEX_NOTE = ("\n\n### Neste modo (Codex)\n"
              "O servidor MCP `trader` (modo B3) está conectado, mas as tools NÃO aparecem soltas na sua lista: chame-as "
              "por dentro do `functions.exec` (ex.: b3_preflight, get_morning_dossier, write_day_plan). Nunca conclua que "
              "estão indisponíveis sem antes tentar chamar o b3_preflight pelo functions.exec.\n")


def prompt(kind: str) -> str:
    rules = (ROOT / "CLAUDE_B3.md").read_text(encoding="utf-8").split("## Operador", 1)[1]
    return "# Instruções do operador B3" + rules + CODEX_NOTE + "\n" + PROMPT[kind]


def loop_revise() -> int:
    """Revisão a cada session.revise_every_min até no_entry_after (o agendador ou o b3_hoje.bat chamam)."""
    from trader.b3.config import hhmm, load_b3
    from trader.trading_b3 import TZ
    while True:
        s = load_b3()["session"]
        if datetime.now(TZ).time() >= hhmm(s["no_entry_after"]):
            return 0
        main(["--kind", "revise"])
        time.sleep(s["revise_every_min"] * 60)


def main(argv: list[str]) -> int:
    if "--loop" in argv:
        return loop_revise()
    kind = argv[argv.index("--kind") + 1] if "--kind" in argv else "plan"
    if kind not in KINDS:
        raise SystemExit(f"--kind deve ser um de {KINDS}")
    cc = cycle_cfg()
    if cc.get("backend") != "codex":
        raise SystemExit("o modo B3 roda só com backend: codex em config/cycle.yaml")
    cycle_id = f"b3{kind}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    schema, last, log = logs / f"{cycle_id}.schema.json", logs / f"{cycle_id}.last.json", logs / f"{cycle_id}.json"
    schema.write_text(json.dumps(SCHEMA[kind]), encoding="utf-8")
    try:
        with exclusive("b3_operator"):
            conn = connect()
            insert(conn, "cycles", {"id": cycle_id, "kind": f"b3_{kind}", "started_at": now_iso(), "status": "running"})
            cmd = build_codex_cmd(kind, cycle_id, cc, None, schema, last, mcp_module="trader.mcp_server_b3")
            env = {**clean_env(), "TRADER_CYCLE_ID": cycle_id, "TRADER_CYCLE_KIND": kind}
            t0 = time.time()
            try:
                with log.open("w", encoding="utf-8") as f:
                    p = subprocess.run(cmd, cwd=ROOT, env=env, input=prompt(kind), stdout=f, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace", timeout=cc["timeout_min"] * 60)
                err = p.stderr
            except subprocess.TimeoutExpired:
                err = f"TIMEOUT após {cc['timeout_min']} min"
            result = parse_codex(log.read_text(encoding="utf-8"), last)
            ran = kind in ("close", "weekly") or get_state(conn, "b3_last_preflight") == cycle_id
            status = classify(result, err, ran)
            so = result.get("structured_output") or {}
            update(conn, "cycles", cycle_id, {"ended_at": now_iso(), "status": status,
                                              "input_tokens": (result.get("usage") or {}).get("input_tokens"),
                                              "output_tokens": (result.get("usage") or {}).get("output_tokens"),
                                              "summary_json": json.dumps({"out": so, "secs": round(time.time() - t0)},
                                                                         default=str)[:20000]})
            if status.startswith("error"):
                notify(f"❗ B3 {kind} {cycle_id} falhou ({status}). Veja data/logs.\n{(err or '')[-400:]}")
            elif kind == "plan" and not so.get("plan_written"):
                notify(f"🟡 B3: sem plano hoje (dia sem operação). {so.get('summary', '')[:800]}")
            elif kind in ("close", "weekly"):
                notify(f"📓 B3 {kind}: {so.get('summary', '')[:1500]}")
            print(json.dumps({"cycle": cycle_id, "status": status, "structured_output": so}, ensure_ascii=False, indent=1))
            return 0 if not status.startswith("error") else 1
    except BlockingIOError:
        print("outra execução do operador B3 em andamento; saindo")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
