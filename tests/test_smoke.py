from trader import smoke
from trader.collectors import market, news


def test_smoke_sim_passa_tudo(monkeypatch, capsys):
    monkeypatch.setattr(market, "collect", lambda: {"ewz": "indisponível"})
    monkeypatch.setattr(news, "collect", lambda: {"items": [], "failed_sources": [], "note": ""})
    assert smoke.run(sim=True, no_llm=True)
    out = capsys.readouterr().out
    assert "FALHOU" not in out and "OK] watchdog: posição sem SL" in out
