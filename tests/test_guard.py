import json
import os
import subprocess
import sys
from pathlib import Path

GUARD = Path(__file__).parents[1] / "hooks" / "guard.py"


def run(payload, cycle=True):
    env = {k: v for k, v in os.environ.items() if k != "TRADER_CYCLE_ID"}
    if cycle:
        env["TRADER_CYCLE_ID"] = "t1"
    return subprocess.run([sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, env=env).returncode


def test_allows_only_trader_mcp_and_agent():
    assert run(json.dumps({"tool_name": "mcp__trader__place_entry"})) == 0
    assert run(json.dumps({"tool_name": "Agent"})) == 0
    assert run(json.dumps({"tool_name": "StructuredOutput"})) == 0
    for bad in ("Bash", "Read", "Edit", "Write", "WebFetch", "mcp__other__x", "PowerShell", "mcp__traderx__y"):
        assert run(json.dumps({"tool_name": bad})) == 2, bad


def test_fail_closed_on_garbage():
    assert run("não é json") == 2
    assert run(json.dumps([1, 2])) == 2


def test_inactive_outside_cycle():
    assert run(json.dumps({"tool_name": "Bash"}), cycle=False) == 0
