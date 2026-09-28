"""Observatório 3D: vê os ciclos dos agentes (replay e ao vivo) numa sala de trading.

`uv run python -m trader.observatory`  →  http://127.0.0.1:8765

Só leitura: lê data/logs/cycle-*.json (JSONL do codex exec) e a tabela cycles. Não fala com a exchange.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from trader.config import CONFIG_DIR, DATA_DIR, ROOT
from trader.db import connect

PAGE = ROOT / "observatory" / "index.html"
JS_DIR = ROOT / "observatory" / "js"
JS_NAME = re.compile(r"^/js/([a-z]+)\.js$")
LOGS = DATA_DIR / "logs"
CYCLE_ID = re.compile(r"^(cycle|weekly)-\d{8}-\d{6}$")


def result_text(result) -> str:
    if not isinstance(result, dict):
        return ""
    return " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))


def parsed(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def parse_events(text: str) -> list[dict]:
    """JSONL do `codex exec --json` → eventos simples para a cena. Linhas quebradas (arquivo crescendo) são puladas."""
    events = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        item, t = e.get("item") or {}, e.get("type")
        if item.get("type") == "mcp_tool_call":
            ev = {"kind": "tool", "id": item.get("id"), "tool": item.get("tool"), "args": item.get("arguments") or {},
                  "phase": "start" if t == "item.started" else "end"}
            if t == "item.completed":
                text = result_text(item.get("result"))
                ev["data"] = parsed(text)                 # resultado inteiro, já como objeto: a cena escreve as falas
                ev["result"] = text[:600]
                ev["error"] = (item.get("error") or {}).get("message")
            events.append(ev)
        elif item.get("type") == "agent_message" and t == "item.completed":
            events.append({"kind": "message", "text": item.get("text", "")})
        elif t == "turn.completed":
            events.append({"kind": "usage", "usage": e.get("usage") or {}})
        elif t in ("turn.failed", "error"):
            events.append({"kind": "error", "text": json.dumps(e, ensure_ascii=False)[:500]})
    return events


def db_cycles(limit=60) -> dict:
    conn = connect()
    rows = conn.execute("SELECT id, kind, started_at, ended_at, status, input_tokens, output_tokens, summary_json "
                        "FROM cycles ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return {r["id"]: dict(r) for r in rows}


def list_cycles() -> list[dict]:
    db = db_cycles()
    out = []
    for f in sorted(LOGS.glob("*-*.json"), reverse=True):
        cid = f.stem
        if not CYCLE_ID.match(cid):
            continue
        r = db.get(cid, {})
        out.append({"id": cid, "status": r.get("status") or "?", "started_at": r.get("started_at"),
                    "ended_at": r.get("ended_at")})
    return out[:60]


def cycle(cid: str) -> dict | None:
    if not CYCLE_ID.match(cid) or not (LOGS / f"{cid}.json").exists():
        return None
    r = db_cycles(200).get(cid, {})
    summary = json.loads(r["summary_json"]).get("out") if r.get("summary_json") else None
    return {"id": cid, "status": r.get("status") or "?", "started_at": r.get("started_at"),
            "ended_at": r.get("ended_at"), "running": r.get("status") == "running", "summary": summary,
            "events": parse_events((LOGS / f"{cid}.json").read_text(encoding="utf-8", errors="replace"))}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        m = JS_NAME.match(path)
        if m and (JS_DIR / f"{m[1]}.js").is_file():
            return self._send(200, (JS_DIR / f"{m[1]}.js").read_bytes(), "text/javascript; charset=utf-8")
        if path == "/api/meta":
            cc = yaml.safe_load((CONFIG_DIR / "cycle.yaml").read_text(encoding="utf-8"))
            rv = cc.get("codex_reviewers") or {}
            return self._json({"backend": cc.get("backend"), "operator": cc.get("codex_model"),
                               "charts": (rv.get("charts") or {}).get("model"), "bear": (rv.get("bear") or {}).get("model")})
        if path == "/api/cycles":
            return self._json(list_cycles())
        if path.startswith("/api/cycle/"):
            c = cycle(path.rsplit("/", 1)[1])
            return self._json(c) if c else self._json({"error": "not found"}, 404)
        self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


def main(argv: list[str]) -> None:
    port = int(argv[0]) if argv else 8765
    print(f"Observatório em http://127.0.0.1:{port}  (Ctrl+C para sair)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
