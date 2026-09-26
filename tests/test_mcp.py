import asyncio
import json

import pytest
from fastmcp import Client

from fake_exchange import FakeExchange
from test_sync import make_cfg
from trader import mcp_server
from trader.db import connect, set_state
from trader.trading import Ctx

EXPECTED = {"preflight", "sync_positions", "get_regime", "scan_market", "get_candles", "get_portfolio",
            "get_setup_stats", "get_recent_journal", "get_pending_postmortems", "get_safety_status", "place_entry",
            "move_stop", "take_partial", "close_position", "write_journal", "write_proposal"}


@pytest.fixture
def server(rules, monkeypatch):
    ex = FakeExchange(rules, {"BTC/USDT": 65000, "USDT/BRL": 5.4}, {"USDT": 90})
    ex.redact = lambda t: t.replace("SEGREDO123", "***")
    c = Ctx(connect(":memory:"), ex, make_cfg("dry"), cycle_id="manual", notify=lambda m: None, sleep=lambda s: None)
    monkeypatch.setattr(mcp_server, "_ctx", c)
    monkeypatch.setattr(mcp_server, "_regime_cache", (1e18, {"regime": "BULL"}))
    return c


def call(name, args=None):
    async def go():
        async with Client(mcp_server.mcp) as cl:
            return await cl.call_tool(name, args or {}, raise_on_error=False)
    return asyncio.run(go())


def test_tool_surface_has_no_dangerous_tools():
    async def go():
        async with Client(mcp_server.mcp) as cl:
            return await cl.list_tools()
    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == EXPECTED
    for t in tools.values():
        props = t.input_schema.get("properties", {})
        assert not {"amount", "qty", "quantity", "size", "notional", "address"} & set(props), t.name
    assert tools["place_entry"].input_schema["properties"]["symbol"]["pattern"]


def test_bad_symbol_rejected_by_schema(server):
    r = call("place_entry", {"symbol": "BTC/USDT; rm -rf", "horizon": "swing", "setup": "x_y_z",
                             "stop_price": 1, "target_price": 2, "reason": "abc"})
    assert r.is_error


def test_entry_requires_symbol_from_this_cycle_scan(server):
    args = {"symbol": "BTC/USDT", "horizon": "swing", "setup": "swing_breakout_4h",
            "stop_price": 62400, "target_price": 70200, "reason": "rompimento"}
    r = call("place_entry", args)
    assert r.is_error and "NOT_IN_UNIVERSE" in r.content[0].text
    set_state(server.conn, "last_scan", {"cycle_id": "manual", "passed": ["BTC/USDT"]})
    r = call("place_entry", args)
    assert not r.is_error and r.structured_content["dry_run"] is True


def test_secrets_redacted_from_output(server):
    server.ex.ticker = lambda s: {"last": 1.0, "bid": 1, "ask": 1, "junk": "SEGREDO123"}
    set_state(server.conn, "last_scan", {"cycle_id": "manual", "passed": ["BTC/USDT"]})
    r = call("write_journal", {"kind": "cycle_note", "thesis": "chave SEGREDO123 vazou?"})
    assert not r.is_error
    j = call("get_recent_journal", {"n": 5})
    assert "SEGREDO123" not in json.dumps(j.structured_content)


def test_weekly_cannot_trade(server, monkeypatch):
    monkeypatch.setattr(mcp_server, "CYCLE_KIND", "weekly")
    r = call("close_position", {"symbol": "BTC/USDT", "reason": "teste"})
    assert r.is_error and "READ_ONLY" in r.content[0].text
    r = call("write_proposal", {"title": "Subir risco", "body": "proposta de teste com texto"})
    assert not r.is_error


def test_proposal_blocked_outside_weekly(server):
    r = call("write_proposal", {"title": "x" * 5, "body": "y" * 20})
    assert r.is_error and "WEEKLY_ONLY" in r.content[0].text
