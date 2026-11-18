# -*- coding: utf-8 -*-
"""Aba "Analise" do painel: graficos de um combo e da campanha. So le.

Tudo sai do que o circuito ja grava, sem rodar MT5:

- trades do combo: `campanha_relatorios/<relatorio_dir>/conf_wrx.htm` (o mesmo
  relatorio que o Monte Carlo do estagio 4 le, parser `portfolio_builder.ler_html`);
- WFA por janela: `wfa_real_resultados/<simbolo>__<sistema>__<variante>.json`
  (escrito por `wfa_real.py`);
- funil: `campanha_resultados.jsonl` (ultima linha de cada combo, campo
  `reprovado_em`), `sets_implantados.json` e o roster do receptor.

Monte Carlo aqui e o mesmo bootstrap com reposicao de `monte_carlo_wrx.simular`,
so que devolvendo o leque inteiro (faixas por trade) e a distribuicao do pior
drawdown, para desenhar. Medido em dinheiro do relatorio (o deposito do combo),
nao em R: vale para todo sistema, inclusive grid/martingale sem Fixed-R.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from portfolio_builder import ler_html

AQUI = Path(__file__).parent
RELATORIOS_DIR = AQUI / "campanha_relatorios"
WFA_DIR = AQUI / "wfa_real_resultados"

# Ordem em que `optimize_two_stage.decidir_trader` testa os gates (o primeiro
# que falha vira `reprovado_em`). O que vier com outro valor reprovou antes
# da decisao (estagios 1-4: triagem, retencao, tick real).
GATES = [
    ("divergencia", "Divergência OHLC × tick"),
    ("sobrevivencia", "Sobrevivência 3 anos"),
    ("drawdown", "Drawdown"),
    ("nunca_visto", "Dado nunca visto"),
    ("gate_relativo", "Melhor que o campeão"),
]
MAX_PONTOS = 160


def nome_seguro(relatorio_dir: str) -> bool:
    return bool(relatorio_dir) and not any(
        c in relatorio_dir for c in ("/", "\\", "..")) and len(relatorio_dir) < 200


def trades_do_relatorio(htm: Path) -> pd.DataFrame | None:
    """(tempo, lucro) so dos fechamentos: o deal de abertura sai com lucro 0."""
    if not htm.is_file():
        return None
    t = ler_html(htm)
    if t is None or t.empty:
        return None
    t = t.loc[t["lucro"] != 0].sort_values("tempo").reset_index(drop=True)
    return t if len(t) else None


def _amostrar(idx_total: int) -> np.ndarray:
    if idx_total <= MAX_PONTOS:
        return np.arange(idx_total)
    return np.unique(np.linspace(0, idx_total - 1, MAX_PONTOS).round().astype(int))


def curva(trades: pd.DataFrame) -> dict:
    lucro = trades["lucro"].to_numpy(float)
    eq = np.cumsum(lucro)
    pico = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    dd = eq - pico
    idx = _amostrar(len(eq))
    vit = lucro[lucro > 0]
    der = lucro[lucro < 0]
    return {
        "t": [trades["tempo"].iloc[i].strftime("%Y-%m-%d") for i in idx],
        "equity": [round(float(eq[i]), 2) for i in idx],
        "dd": [round(float(dd[i]), 2) for i in idx],
        "n": int(len(lucro)),
        "lucro": round(float(eq[-1]), 2),
        "dd_max": round(float(dd.min()), 2),
        "win_rate": round(100.0 * len(vit) / len(lucro), 1),
        "profit_factor": (round(float(vit.sum() / -der.sum()), 2)
                          if len(der) and der.sum() < 0 else None),
        "media": round(float(lucro.mean()), 2),
        "desvio": round(float(lucro.std(ddof=1)), 2) if len(lucro) > 1 else None,
    }


def monte_carlo(lucro: np.ndarray, n: int = 500, seed: int = 7) -> dict | None:
    """Leque do bootstrap: percentis 5/25/50/75/95 da equity a cada trade e o
    histograma do pior drawdown das N reamostras."""
    if len(lucro) < 5:
        return None
    rng = np.random.default_rng(seed)
    amostras = lucro[rng.integers(0, len(lucro), size=(n, len(lucro)))]
    curvas = np.cumsum(amostras, axis=1)
    picos = np.maximum.accumulate(np.maximum(curvas, 0.0), axis=1)
    piores = (curvas - picos).min(axis=1)
    idx = _amostrar(len(lucro))
    faixas = {f"p{p}": [round(float(v), 2) for v in
                        np.percentile(curvas[:, idx], p, axis=0)]
              for p in (5, 25, 50, 75, 95)}
    mag = np.abs(piores)
    cont, bordas = np.histogram(mag, bins=24)
    eq_obs = np.cumsum(lucro)
    dd_obs = float(abs((eq_obs - np.maximum.accumulate(
        np.maximum(eq_obs, 0.0))).min()))
    return {
        "n": n, "trades": int(len(lucro)), "x": [int(i) + 1 for i in idx],
        **faixas,
        "observada": [round(float(eq_obs[i]), 2) for i in idx],
        "dd_hist": {"contagem": [int(c) for c in cont],
                    "bordas": [round(float(b), 2) for b in bordas]},
        "dd_observado": round(dd_obs, 2),
        "dd_p50": round(float(np.percentile(mag, 50)), 2),
        "dd_p95": round(float(np.percentile(mag, 95)), 2),
        "prob_prejuizo": round(float((curvas[:, -1] < 0).mean()), 4),
        "final_p5": round(float(np.percentile(curvas[:, -1], 5)), 2),
        "final_p95": round(float(np.percentile(curvas[:, -1], 95)), 2),
    }


def mensal(trades: pd.DataFrame) -> dict:
    s = trades.set_index("tempo")["lucro"]
    por_mes = s.groupby([s.index.year, s.index.month]).sum()
    anos: dict[str, list] = {}
    for (ano, mes), v in por_mes.items():
        anos.setdefault(str(ano), [None] * 12)[mes - 1] = round(float(v), 2)
    return {"anos": dict(sorted(anos.items())),
            "max_abs": round(float(por_mes.abs().max()), 2) if len(por_mes) else 0}


def wfa(chave: str, base: Path | None = None) -> dict | None:
    caminho = (base or WFA_DIR) / f"{chave}.json"
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    w = d.get("wfa") or {}
    janelas = [{"janela": j.get("janela"), "is": j.get("is"), "oos": j.get("oos"),
                "lucro_is": j.get("lucro_is"), "lucro_oos": j.get("lucro_oos"),
                "wfe_pct": j.get("wfe_pct"), "motivo": j.get("motivo")}
               for j in w.get("detalhe") or []]
    if not janelas and not d.get("holdout"):
        return None
    return {"janelas": janelas, "wfe_global_pct": w.get("wfe_global_pct"),
            "wfe_media_pct": w.get("wfe_media_pct"),
            "ciclos_positivos": w.get("ciclos_positivos"),
            "is_dias": w.get("is_dias"), "oos_dias": w.get("oos_dias"),
            "holdout": d.get("holdout")}


def analisar(relatorio_dir: str, chave: str | None = None,
             base: Path | None = None, wfa_base: Path | None = None) -> dict:
    if not nome_seguro(relatorio_dir):
        return {"ok": False, "erro": "parametro invalido"}
    trades = trades_do_relatorio((base or RELATORIOS_DIR) / relatorio_dir
                                 / "conf_wrx.htm")
    if trades is None:
        return {"ok": False, "erro": "relatorio sem trades legiveis nesta maquina"}
    return {"ok": True, "relatorio_dir": relatorio_dir, "chave": chave,
            "curva": curva(trades),
            "monte_carlo": monte_carlo(trades["lucro"].to_numpy(float)),
            "mensal": mensal(trades),
            "wfa": wfa(chave, wfa_base) if chave else None}


def chave_da_linha(r: dict) -> str:
    return (f"{str(r.get('simbolo', '')).replace('.', '_')}__"
            f"{r.get('sistema', '')}__{r.get('variante', '')}")


def ultima_por_combo(ledger: list[dict]) -> dict[str, dict]:
    vigente: dict[str, dict] = {}
    for r in ledger:
        if r.get("sistema") and r.get("simbolo"):
            vigente[chave_da_linha(r)] = r
    return vigente


def combos(ledger: list[dict], vivos: set[str] | None = None,
           base: Path | None = None) -> list[dict]:
    """Combos com relatorio arquivado NESTA maquina: no live primeiro, depois
    aprovados, depois o resto por lucro OOS."""
    vivos = vivos or set()
    raiz = base or RELATORIOS_DIR
    saida = []
    for chave, r in ultima_por_combo(ledger).items():
        rd = r.get("relatorio_dir")
        if not (rd and nome_seguro(rd) and (raiz / rd / "conf_wrx.htm").is_file()):
            continue
        saida.append({"chave": chave, "relatorio_dir": rd,
                      "aprovado": bool(r.get("aprovado")),
                      "ao_vivo": chave in vivos,
                      "reprovado_em": r.get("reprovado_em"),
                      "lucro_oos": r.get("lucro_oos")})
    saida.sort(key=lambda c: (not c["ao_vivo"], not c["aprovado"],
                              -(c["lucro_oos"] or -1e18)))
    return saida


def funil(ledger: list[dict], implantados: set[str], vivos: set[str]) -> dict:
    """Testados -> estagios 1-4 -> cada gate da decisao -> aprovados ->
    implantados -> rodando no receptor. Ultima linha de cada combo."""
    vig = ultima_por_combo(ledger)
    total = len(vig)
    por_motivo: dict[str, int] = {}
    for r in vig.values():
        if not r.get("aprovado"):
            m = r.get("reprovado_em") or "antes"
            por_motivo[m] = por_motivo.get(m, 0) + 1
    conhecidos = {g for g, _ in GATES}
    antes = sum(v for k, v in por_motivo.items() if k not in conhecidos)
    etapas = [{"rotulo": "Combos testados", "n": total, "caiu": 0}]
    resta = total - antes
    etapas.append({"rotulo": "Passaram triagem, retenção e tick real",
                   "n": resta, "caiu": antes})
    for g, rotulo in GATES:
        caiu = por_motivo.get(g, 0)
        resta -= caiu
        etapas.append({"rotulo": rotulo, "n": resta, "caiu": caiu})
    aprovados = sum(1 for r in vig.values() if r.get("aprovado"))
    etapas.append({"rotulo": "Implantados", "n": len(implantados & set(vig)) or len(implantados),
                   "caiu": None})
    etapas.append({"rotulo": "Rodando no receptor", "n": len(vivos), "caiu": None})
    return {"total": total, "aprovados": aprovados, "etapas": etapas}


def correlacao(itens: list[tuple[str, Path]], maximo: int = 12) -> dict | None:
    """Pearson do resultado diario entre combos (dias sem trade = 0)."""
    series = {}
    for chave, htm in itens[:maximo]:
        t = trades_do_relatorio(htm)
        if t is not None:
            series[chave] = t.groupby(t["tempo"].dt.normalize())["lucro"].sum()
    if len(series) < 2:
        return None
    df = pd.DataFrame(series).fillna(0.0)
    m = df.corr().to_numpy()
    return {"nomes": list(df.columns),
            "matriz": [[None if math.isnan(v) else round(float(v), 2) for v in linha]
                       for linha in m],
            "dias": int(len(df))}


def ao_vivo_vs_teste(slot: dict, trades: pd.DataFrame | None,
                     n_sim: int = 2000, seed: int = 11) -> dict:
    """Resultado ao vivo do slot contra o que o teste dava para o MESMO numero
    de trades: faixa p5-p95 do bootstrap dos trades do relatorio (se houver
    nesta maquina) ou so o ritmo esperado do dado nunca visto do motor.
    Escala: o capital do slot sobre o deposito do teste nao e conhecido aqui,
    entao a comparacao e por trade, em dinheiro do teste, so como ordem de
    grandeza; o veredito continua sendo o da incubacao."""
    n = int(slot.get("fechados") or 0)
    real = slot.get("net_virtual")
    nv = ((slot.get("teste") or {}).get("nunca_visto") or {})
    esperado_trade = (nv["lucro"] / nv["trades"]
                      if nv.get("lucro") is not None and nv.get("trades") else None)
    saida = {"n": n, "real": real, "esperado_por_trade": (
        round(esperado_trade, 2) if esperado_trade is not None else None),
        "esperado": (round(esperado_trade * n, 2)
                     if esperado_trade is not None else None),
        "p5": None, "p95": None, "fonte": "nunca_visto" if esperado_trade is not None else None}
    if trades is not None and n > 0 and len(trades) >= 5:
        lucro = trades["lucro"].to_numpy(float)
        rng = np.random.default_rng(seed)
        somas = lucro[rng.integers(0, len(lucro), size=(n_sim, n))].sum(axis=1)
        saida.update(p5=round(float(np.percentile(somas, 5)), 2),
                     p95=round(float(np.percentile(somas, 95)), 2),
                     esperado=round(float(np.median(somas)), 2), fonte="relatorio")
    if real is not None and saida["p5"] is not None:
        saida["fora"] = bool(real < saida["p5"] or real > saida["p95"])
    return saida
