import json

from trader import observatory as ob


def test_parse_events():
    lines = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "vou começar"}},
        {"type": "item.started", "item": {"id": "i1", "type": "mcp_tool_call", "tool": "preflight", "arguments": {}}},
        {"type": "item.completed", "item": {"id": "i1", "type": "mcp_tool_call", "tool": "preflight", "arguments": {},
                                            "result": {"content": [{"type": "text", "text": '{"status":"OK"}'}]}}},
        {"type": "item.completed", "item": {"id": "i2", "type": "mcp_tool_call", "tool": "place_entry", "arguments": {},
                                            "error": {"message": "RECUSADO BEAR_VETO: x"}}},
        {"type": "turn.completed", "usage": {"input_tokens": 9}},
    ]
    text = "\n".join(json.dumps(x) for x in lines) + '\n{"type": "item.star'   # última linha ainda sendo escrita
    ev = ob.parse_events(text)
    assert [e["kind"] for e in ev] == ["message", "tool", "tool", "tool", "usage"]
    assert ev[1]["phase"] == "start" and ev[2]["data"] == {"status": "OK"}
    assert ev[3]["error"] == "RECUSADO BEAR_VETO: x"


def test_cycle_id_valida_caminho():
    assert ob.cycle("../config/.env") is None and ob.cycle("cycle-1") is None


def test_summary_message_preserves_valid_json():
    summary = {"actions": [{"detail": "Motivo detalhado. " * 120}], "summary": "Sem nova entrada."}
    message = json.dumps(summary)
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": message}}
    parsed = ob.parse_events(json.dumps(event))
    assert json.loads(parsed[0]["text"])["summary"] == "Sem nova entrada."
