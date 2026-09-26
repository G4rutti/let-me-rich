"""PreToolUse hook fail-closed para os ciclos headless.

Só age quando TRADER_CYCLE_ID está definido (setado pelo run_cycle): em sessões de desenvolvimento não interfere.
No ciclo, permite apenas tools do MCP "trader", o Agent (subagentes) e o StructuredOutput (--json-schema). Qualquer erro aqui = bloqueia (exit 2).
"""
import json
import os
import sys


def main() -> int:
    if not os.environ.get("TRADER_CYCLE_ID"):
        return 0
    try:
        tool = json.load(sys.stdin).get("tool_name", "")
        if tool.startswith("mcp__trader__") or tool in ("Agent", "StructuredOutput"):
            return 0
        print(f"bloqueado pelo guard do ciclo: {tool} não é permitido", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — fail-closed
        print(f"guard falhou ({type(e).__name__}); bloqueando", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
