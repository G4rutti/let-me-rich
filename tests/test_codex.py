import json

from trader import run_cycle as rc


def test_codex_cmd_travado(tmp_path, monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda _: "codex")
    cc = {"codex_model": "m", "codex_effort": "low"}
    cmd = rc.build_codex_cmd("cycle", "c1", cc, None, tmp_path / "s.json", tmp_path / "l.json")
    assert ["-s", "read-only"] == cmd[cmd.index("-s"):cmd.index("-s") + 2]
    assert "--ephemeral" in cmd and cmd[-1] == "-"
    for f in ("shell_tool", "unified_exec", "multi_agent", "browser_use", "computer_use"):
        assert f in cmd[cmd.index("--disable"):]
    assert 'mcp_servers.trader.env={TRADER_CYCLE_ID="c1",TRADER_CYCLE_KIND="cycle"}' in cmd


def test_codex_prompt_tem_regras():
    p = rc.codex_prompt("cycle")
    assert "preflight" in p and "bear-reviewer" in p and "Neste modo (Codex)" in p


def test_parse_codex(tmp_path):
    last = tmp_path / "l.json"
    out = "\n".join(json.dumps(e) for e in [{"type": "thread.started"}, {"type": "turn.completed", "usage": {"input_tokens": 5}}])
    assert rc.parse_codex(out, last) == {}                       # sem resposta final = erro
    last.write_text('{"preflight_status": "OK"}', encoding="utf-8")
    r = rc.parse_codex(out, last)
    assert r["structured_output"] == {"preflight_status": "OK"} and r["usage"] == {"input_tokens": 5}
    assert rc.classify(r, "", True) == "ok"
    assert rc.parse_codex(out + '\n{"type": "turn.failed"}', last)["is_error"]
