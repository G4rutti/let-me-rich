import json
from pathlib import Path

import pytest

from trader.exchange import rules_from_info

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def exinfo():
    return json.loads((FIX / "exchange_info.json").read_text())


@pytest.fixture(scope="session")
def rules(exinfo):
    return {f"{v['baseAsset']}/USDT": rules_from_info(f"{v['baseAsset']}/USDT", v) for v in exinfo.values()}


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Testes nunca escrevem no audit/lock reais em data/."""
    import trader.journal
    import trader.lock
    monkeypatch.setattr(trader.journal, "DATA_DIR", tmp_path)
    monkeypatch.setattr(trader.lock, "DATA_DIR", tmp_path)
