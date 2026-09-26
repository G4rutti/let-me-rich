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
