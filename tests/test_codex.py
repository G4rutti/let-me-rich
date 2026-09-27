import json
from pathlib import Path

import pytest

from test_mcp import call, server  # noqa: F401 — fixture
from trader import codex, mcp_server, run_cycle as rc
from trader.db import set_state


def test_codex_cmd_travado(tmp_path, monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda _: "codex")
    cc = {"codex_model": "m", "codex_effort": "low"}
    cmd = rc.build_codex_cmd("cycle", "c1", cc, None, tmp_path / "s.json", tmp_path / "l.json")
    assert ["-s", "read-only"] == cmd[cmd.index("-s"):cmd.index("-s") + 2]
    assert "--ephemeral" in cmd and cmd[-1] == "-" and "mcp_servers.trader.required=true" in cmd
    for f in ("shell_tool", "unified_exec", "multi_agent", "browser_use", "computer_use"):
        assert f in cmd[cmd.index("--disable"):]
    assert 'mcp_servers.trader.env={TRADER_CYCLE_ID="c1",TRADER_CYCLE_KIND="cycle",TRADER_BACKEND="codex"}' in cmd


def test_codex_prompt_tem_regras():
    p = rc.codex_prompt("cycle")
    assert "preflight" in p and "read_charts" in p and "BEAR_VETO" in p


def test_parse_codex(tmp_path):
    last = tmp_path / "l.json"
    out = "\n".join(json.dumps(e) for e in [{"type": "thread.started"}, {"type": "turn.completed", "usage": {"input_tokens": 5}}])
    assert rc.parse_codex(out, last) == {}                       # sem resposta final = erro
    last.write_text('{"preflight_status": "OK"}', encoding="utf-8")
    r = rc.parse_codex(out, last)
    assert r["structured_output"] == {"preflight_status": "OK"} and r["usage"] == {"input_tokens": 5}
    assert rc.classify(r, "", True) == "ok"
    assert rc.parse_codex(out + '\n{"type": "turn.failed"}', last)["is_error"]


def test_ask_sem_tools():
    cmd = codex.ask_cmd({"codex_path": "codex"}, "m", "low", Path("s"), Path("l"))
    assert "mcp_servers" not in " ".join(cmd) and "code_mode_host" in cmd and "--ephemeral" in cmd
    assert ["-s", "read-only"] == cmd[cmd.index("-s"):cmd.index("-s") + 2]


ENTRY = {"symbol": "BTC/USDT", "horizon": "swing", "setup": "swing_breakout_4h",
         "stop_price": 62400, "target_price": 70200, "reason": "rompimento"}


def _codex_entry(server, monkeypatch, answer):
    monkeypatch.setattr(mcp_server, "BACKEND", "codex")
    seen = []

    def fake_ask(role, instructions, data, schema):
        seen.append((role, data))
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(codex, "ask", fake_ask)
    set_state(server.conn, "last_scan", {"cycle_id": "manual", "passed": ["BTC/USDT"]})
    return call("place_entry", ENTRY), seen


def test_bear_veta(server, monkeypatch):
    r, seen = _codex_entry(server, monkeypatch, {"verdict": "VETO", "strength": 4, "against": ["sem volume"]})
    assert r.is_error and "BEAR_VETO" in r.content[0].text and "sem volume" in r.content[0].text
    assert seen[0][0] == "bear" and set(seen[0][1]["charts"]) == {"1h", "4h"}
    assert not server.conn.execute("SELECT 1 FROM trades").fetchone()


def test_bear_libera(server, monkeypatch):
    r, _ = _codex_entry(server, monkeypatch, {"verdict": "SEM_VETO", "strength": 2, "against": ["x"]})
    assert not r.is_error and r.structured_content["bear_review"]["strength"] == 2


def test_revisor_falhou_recusa(server, monkeypatch):
    r, _ = _codex_entry(server, monkeypatch, codex.CodexError("bear: timeout"))
    assert r.is_error and "REVIEW_FAILED" in r.content[0].text


def test_claude_nao_chama_revisor(server, monkeypatch):
    monkeypatch.setattr(codex, "ask", lambda *a: pytest.fail("não devia revisar"))
    set_state(server.conn, "last_scan", {"cycle_id": "manual", "passed": ["BTC/USDT"]})
    assert not call("place_entry", ENTRY).is_error


def test_read_charts(server, monkeypatch):
    monkeypatch.setattr(codex, "ask", lambda role, i, data, s: {"pairs": [], "role": role, "n": list(data["pairs"])})
    r = call("read_charts", {"symbols": ["BTC/USDT"]})
    assert not r.is_error and r.structured_content["role"] == "charts" and r.structured_content["n"] == ["BTC/USDT"]
