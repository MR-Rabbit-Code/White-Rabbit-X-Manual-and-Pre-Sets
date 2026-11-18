# -*- coding: utf-8 -*-
"""Aba Analise: curva, Monte Carlo, mensal, WFA, funil, correlacao e ao vivo x teste."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

import analise_wrx as a  # noqa: E402


def _htm(pasta: Path, lucros: list[float], inicio: str = "2025-01-02") -> Path:
    import pandas as pd
    datas = pd.date_range(inicio, periods=len(lucros), freq="3D")
    linhas = "".join(
        f"<tr><td>{d:%Y.%m.%d %H:%M:%S}</td><td>{i}</td><td>buy</td><td>{v}</td></tr>"
        for i, (d, v) in enumerate(zip(datas, lucros)))
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / "conf_wrx.htm"
    caminho.write_text("<html><body><table><tr><th>Time</th><th>Deal</th><th>Type</th>"
                       f"<th>Profit</th></tr>{linhas}</table></body></html>", encoding="utf-8")
    return caminho


def test_analisar_combo_completo(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    lucros = list(np.round(rng.normal(5, 20, 300), 2))
    _htm(tmp_path / "rel" / "EURJPY__03", lucros)
    (tmp_path / "wfa").mkdir()
    (tmp_path / "wfa" / "EURJPY__03_TRAIL_ONLY__BOTH_ICHIMOKU.json").write_text(json.dumps(
        {"wfa": {"wfe_global_pct": 61.0, "ciclos_positivos": "3/4", "detalhe": [
            {"janela": 1, "is": ["a", "b"], "oos": ["b", "c"], "lucro_is": 100, "lucro_oos": 40,
             "wfe_pct": 55.0}]}}), encoding="utf-8")
    r = a.analisar("EURJPY__03", "EURJPY__03_TRAIL_ONLY__BOTH_ICHIMOKU",
                   tmp_path / "rel", tmp_path / "wfa")
    assert r["ok"]
    c = r["curva"]
    assert c["n"] == 300 and len(c["equity"]) <= a.MAX_PONTOS
    assert abs(c["lucro"] - round(sum(lucros), 2)) < 0.05
    assert c["dd_max"] <= 0
    mc = r["monte_carlo"]
    assert all(lo <= hi for lo, hi in zip(mc["p5"], mc["p95"]))
    assert sum(mc["dd_hist"]["contagem"]) == mc["n"]
    assert mc["dd_p95"] >= mc["dd_p50"] >= 0
    total_mensal = sum(v for meses in r["mensal"]["anos"].values() for v in meses if v)
    assert abs(total_mensal - sum(lucros)) < 0.1
    assert r["wfa"]["janelas"][0]["wfe_pct"] == 55.0


def test_nome_inseguro_e_relatorio_ausente(tmp_path: Path) -> None:
    assert not a.analisar("../x", None, tmp_path)["ok"]
    assert not a.analisar("nao_existe", None, tmp_path)["ok"]


def test_funil_soma_e_ordem() -> None:
    def linha(sim, ok, motivo=None):
        return {"simbolo": sim, "sistema": "S", "variante": "V", "aprovado": ok, "reprovado_em": motivo}
    ledger = [linha("A", False, "drawdown"), linha("A", True), linha("B", False, "estagio1"),
              linha("C", False, "divergencia"), linha("D", True), linha("E", False, "drawdown")]
    f = a.funil(ledger, {"A__S__V"}, {"A__S__V"})
    assert f["total"] == 5 and f["aprovados"] == 2
    ns = [e["n"] for e in f["etapas"]]
    assert ns[:2] == [5, 4]
    gates = f["etapas"][2:2 + len(a.GATES)]
    assert gates[-1]["n"] == 2  # sobra = aprovados
    assert all(x >= y for x, y in zip(ns[:7], ns[1:7]))


def test_correlacao(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    base = list(np.round(rng.normal(0, 10, 60), 2))
    h1 = _htm(tmp_path / "a", base)
    h2 = _htm(tmp_path / "b", [x * 2 for x in base])
    h3 = _htm(tmp_path / "c", list(np.round(rng.normal(0, 10, 60), 2)))
    c = a.correlacao([("a", h1), ("b", h2), ("c", h3)])
    assert c["matriz"][0][1] > 0.99 and abs(c["matriz"][0][2]) < 0.5


def test_ao_vivo_vs_teste(tmp_path: Path) -> None:
    import pandas as pd
    slot = {"fechados": 10, "net_virtual": -500.0,
            "teste": {"nunca_visto": {"lucro": 300.0, "trades": 30}}}
    sem = a.ao_vivo_vs_teste(slot, None)
    assert sem["esperado"] == 100.0 and sem["fonte"] == "nunca_visto" and "fora" not in sem
    trades = pd.DataFrame({"tempo": pd.date_range("2025-01-01", periods=50),
                           "lucro": np.random.default_rng(5).normal(10, 5, 50)})
    com = a.ao_vivo_vs_teste(slot, trades)
    assert com["fonte"] == "relatorio" and com["p5"] < com["p95"] and com["fora"] is True
