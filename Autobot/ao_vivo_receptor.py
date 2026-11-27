# -*- coding: utf-8 -*-
"""Aba "Ao vivo" do painel (dono, 18/11/2026: "esse sistema esta muito engessado ao treino manual; da uma atencao na parte do live").

O live do White Rabbit e o RECEPTOR (motor WRX replicando os slots na conta demo + book virtual), que grava em
`<raiz>/_execucao/WhiteRabbit/`:
  receptor/status.json          o retrato do ciclo (conta, slots com saldo virtual, abertas, orfas, vetos, ultimo tick, book)
  receptor/eventos-AAAAMMDD.jsonl  abrir / fechar / slot_rebase / sem_ticks ...
  receptor/virtual/curva.jsonl  equity do book virtual minuto a minuto
  live/slots.json               o roster: por slot, capital, incubacao, desde quando, e a medida do motor (p, n_oos, nota, nunca visto)
  ../troca/whiterabbit/aplicado.json  recibo do pacote aplicado, com versao e contagem de campeoes/incubacao/candidatos
Este modulo so LE e junta tudo num JSON para o painel. Nunca escreve no receptor nem fala com o MT5.
Onde procura: `WRX_RECEPTOR_DIR` (pasta `_execucao/WhiteRabbit`), senao `<raiz>/_execucao/WhiteRabbit` (raiz = pasta acima do repo).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INCUBACAO_ALVO = 30          # trades ao vivo para a incubacao concluir (mesmo N_OOS_MIN do gate comum da Mesa)
TICK_VELHO_S = 15 * 60
RETRATO_VELHO_S = 10 * 60
EVENTOS_MAX = 60
CURVA_MAX = 600


def pasta() -> Path:
    env = os.environ.get("WRX_RECEPTOR_DIR")
    return Path(env) if env else REPO.parent / "_execucao" / "WhiteRabbit"


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _jsonl(p: Path, maximo: int) -> list[dict]:
    try:
        linhas = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for l in linhas[-maximo * 4:]:
        try:
            d = json.loads(l, strict=False)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out[-maximo:]


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _pacote_aplicado(base: Path) -> dict:
    caminho = base.parent / "troca" / "whiterabbit" / "aplicado.json"
    try:
        d = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"estado": "ausente"}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"estado": "invalido", "motivo": type(exc).__name__}
    if not isinstance(d, dict):
        return {"estado": "invalido", "motivo": "schema_invalido"}
    partes = d.get("partes")
    if (d.get("sistema") != "whiterabbit"
            or isinstance(d.get("versao"), bool)
            or not isinstance(d.get("versao"), int)
            or not isinstance(d.get("aplicado_em"), str)
            or not d["aplicado_em"].strip()
            or not isinstance(partes, dict)
            or any(isinstance(partes.get(k), bool)
                   or not isinstance(partes.get(k), int)
                   or partes[k] < 0
                   for k in ("campeoes", "incubacao", "candidatos"))):
        return {"estado": "invalido", "motivo": "schema_invalido"}
    return {
        "estado": "confirmado",
        "versao": d["versao"],
        "aplicado_em": d["aplicado_em"],
        "partes": {k: partes[k] for k in ("campeoes", "incubacao", "candidatos")},
    }


def _sev_slot(s: dict, agora: float) -> tuple[str, str]:
    """(estado, palavra) no padrao da Mesa: ok / warn / bad / off."""
    ef = s.get("estado_efetivo")
    if ef == "DRENANDO":
        return "off", "drenado (saiu do roster)" if s.get("fase") == "drenado" else "drenando: fecha o que tem e não abre"
    if ef not in (None, "ON") or s.get("parado"):
        return "off", "desligado" if ef == "OFF" else "parado"
    if s.get("orfas"):
        return "bad", "posição órfã"
    tick = _num(s.get("ultimo_tick_ms"))
    if tick is None:
        return "warn", "sem tick ainda"
    idade = agora - tick / 1000
    if idade > 2 * 3600:
        return "warn", f"sem tick há {idade / 3600:.0f} h (mercado fechado?)"
    if idade > TICK_VELHO_S:
        return "warn", f"sem tick há {idade / 60:.0f} min"
    if s.get("vetados"):
        return "warn", "com vetos"
    return "ok", "rodando"


def carregar(agora: float | None = None, base: Path | None = None) -> dict:
    agora = agora or time.time()
    base = base or pasta()
    st = _json(base / "receptor" / "status.json")
    roster = _json(base / "live" / "slots.json") or {}
    if not isinstance(st, dict):
        return {"ok": False, "pasta": str(base),
                "erro": "receptor sem status.json nesta máquina (ele roda onde a conta demo do White Rabbit opera)",
                "pacote_aplicado": _pacote_aplicado(base)}
    meta = {x.get("id"): x for x in (roster.get("slots") or []) if isinstance(x, dict)}
    evs = []
    for p in sorted((base / "receptor").glob("eventos-*.jsonl"))[-3:]:
        evs += _jsonl(p, EVENTOS_MAX)
    evs = sorted((e for e in evs if _num(e.get("ts"))), key=lambda e: e["ts"])[-EVENTOS_MAX:]
    fechados_por_slot: dict[str, int] = {}
    for e in evs:
        if e.get("tipo") == "fechar":
            fechados_por_slot[e.get("slot")] = fechados_por_slot.get(e.get("slot"), 0) + 1
    slots = []
    for s in st.get("slots") or []:
        if not isinstance(s, dict):
            continue
        m = meta.get(s.get("id")) or {}
        mot = m.get("motor") or {}
        sev, palavra = _sev_slot(s, agora)
        dep, saldo = _num(s.get("deposito")), _num(s.get("saldo_virtual"))
        fech = int(_num(s.get("fechados_motor")) or 0)
        tick = _num(s.get("ultimo_tick_ms"))
        slots.append({
            "id": s.get("id"), "simbolo": s.get("simbolo"), "magic": s.get("magic"), "estado": sev, "palavra": palavra,
            "fase": s.get("fase"), "incubacao": bool(s.get("incubacao")), "incubacao_fase": m.get("incubacao_fase"),
            "vivo_desde": m.get("vivo_desde"), "deposito": dep, "saldo_virtual": saldo,
            "net_virtual": _num(s.get("net_virtual")), "retorno_pct": (saldo / dep - 1) * 100 if dep and saldo is not None else None,
            "fechados": fech, "progresso_incubacao": min(1.0, fech / INCUBACAO_ALVO),
            "abertas_motor": s.get("abertas_motor"), "abertas_terminal": s.get("abertas_terminal"), "orfas": s.get("orfas"),
            "vetados": s.get("vetados"), "pulos": s.get("pulos") or {}, "piso": bool(s.get("piso")),
            "idade_tick_s": None if tick is None else max(0, agora - tick / 1000),
            "teste": {"p": _num(mot.get("p")), "p_bruto": _num(mot.get("p_bruto")), "n_oos": mot.get("n_oos"), "nota": mot.get("nota"),
                      "nunca_visto": mot.get("nunca_visto"), "lacrado": mot.get("lacrado"), "dd_3anos_pct": _num(mot.get("dd_3anos_pct")),
                      "score": _num(mot.get("composite_score")), "validade_ate": mot.get("validade_ate")},
        })
    ordem = {"bad": 0, "warn": 1, "ok": 2, "off": 3}
    slots.sort(key=lambda x: (ordem.get(x["estado"], 4), str(x["id"])))
    curva = [[d.get("t"), _num(d.get("equity"))] for d in _jsonl(base / "receptor" / "virtual" / "curva.jsonl", CURVA_MAX * 3) if _num(d.get("equity"))]
    passo = max(1, len(curva) // CURVA_MAX)
    atual = _num(st.get("atualizado_em"))
    idade = None if atual is None else max(0, agora - atual)
    conta = st.get("conta") or {}
    book = st.get("book_virtual") or {}
    return {
        "ok": True, "pasta": str(base), "modo": st.get("modo"), "somente_demo": st.get("somente_demo"),
        "idade_s": idade, "retrato_velho": idade is None or idade > RETRATO_VELHO_S,
        "conta": {k: conta.get(k) for k in ("login", "servidor", "moeda", "balance", "equity")},
        "book": {k: book.get(k) for k in ("ativo", "saldo", "equity", "abertas", "erros_seguidos")},
        "piso": st.get("piso_lote_minimo"), "roster_versao": roster.get("versao"), "roster_em": roster.get("gerado_em"),
        "pacote_aplicado": _pacote_aplicado(base),
        "resumo": {"slots": len(slots), "rodando": sum(1 for x in slots if x["estado"] == "ok"),
                   "atencao": sum(1 for x in slots if x["estado"] in ("warn", "bad")),
                   "incubando": sum(1 for x in slots if x["incubacao"]),
                   "abertas": sum(int(x["abertas_terminal"] or 0) for x in slots),
                   "orfas": sum(int(x["orfas"] or 0) for x in slots),
                   "fechados": sum(x["fechados"] for x in slots),
                   "net_virtual": round(sum(x["net_virtual"] or 0 for x in slots), 2),
                   "alvo_incubacao": INCUBACAO_ALVO},
        "slots": slots, "eventos": list(reversed(evs)), "curva": curva[::passo],
    }
