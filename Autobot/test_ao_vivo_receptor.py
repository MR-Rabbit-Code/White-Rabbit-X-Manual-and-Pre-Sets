# -*- coding: utf-8 -*-
"""Aba "Ao vivo" (18/11/2026): junta status.json, slots.json, eventos e curva do receptor; so le."""
import json

import ao_vivo_receptor as A

AGORA = 1794968900.0


def montar(tmp_path, slots, roster=None, eventos=(), curva=()):
    (tmp_path / "receptor" / "virtual").mkdir(parents=True)
    (tmp_path / "live").mkdir()
    st = {"modo": "vivo", "atualizado_em": AGORA - 30, "somente_demo": True, "conta": {"login": "673*****45", "equity": 100230.24},
          "book_virtual": {"ativo": True, "saldo": 99999.98, "equity": 99999.96, "abertas": 1}, "slots": slots}
    (tmp_path / "receptor" / "status.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "live" / "slots.json").write_text(json.dumps(roster or {"versao": 7, "slots": []}), encoding="utf-8")
    (tmp_path / "receptor" / "eventos-20261117.jsonl").write_text("\n".join(json.dumps(e) for e in eventos) + "\nlixo\n", encoding="utf-8")
    (tmp_path / "receptor" / "virtual" / "curva.jsonl").write_text("\n".join(json.dumps(c) for c in curva), encoding="utf-8")
    return tmp_path


def slot(**kw):
    s = {"id": "EURJPY__03", "simbolo": "EURJPY", "magic": 990000002, "estado_efetivo": "ON", "fase": "rodando", "incubacao": True,
         "deposito": 1000.0, "saldo_virtual": 1010.0, "net_virtual": 10.0, "fechados_motor": 3, "abertas_motor": 1, "abertas_terminal": 1,
         "orfas": 0, "vetados": 0, "ultimo_tick_ms": (AGORA - 5) * 1000}
    s.update(kw)
    return s


def test_sem_receptor_diz_onde_procurou(tmp_path):
    r = A.carregar(AGORA, tmp_path)
    assert r["ok"] is False and "status.json" in r["erro"]


def test_junta_roster_eventos_e_curva(tmp_path):
    roster = {"versao": 7, "slots": [{"id": "EURJPY__03", "vivo_desde": "2026-11-16", "incubacao_fase": "coletando",
                                      "motor": {"p": 1.0, "p_bruto": 0.0199, "n_oos": 40, "nota": "FRACA", "nunca_visto": {"lucro": 10, "trades": 40}}}]}
    base = montar(tmp_path, [slot()], roster, eventos=[{"ts": AGORA - 60, "tipo": "fechar", "slot": "EURJPY__03"}],
                  curva=[{"t": "x", "equity": 100000.0}, {"t": "y", "equity": 100001.0}])
    r = A.carregar(AGORA, base)
    s = r["slots"][0]
    assert r["ok"] and s["estado"] == "ok" and s["palavra"] == "rodando"
    assert abs(s["retorno_pct"] - 1.0) < 1e-9 and s["progresso_incubacao"] == 3 / A.INCUBACAO_ALVO
    assert s["teste"]["p_bruto"] == 0.0199 and s["vivo_desde"] == "2026-11-16"
    assert len(r["eventos"]) == 1 and len(r["curva"]) == 2 and r["retrato_velho"] is False
    assert r["resumo"]["net_virtual"] == 10.0


def test_estados_do_slot(tmp_path):
    base = montar(tmp_path, [slot(id="A", orfas=1), slot(id="B", ultimo_tick_ms=(AGORA - 5 * 3600) * 1000),
                             slot(id="C", estado_efetivo="DRENANDO", fase="drenado"), slot(id="D", vetados=2)])
    r = {x["id"]: x for x in A.carregar(AGORA, base)["slots"]}
    assert r["A"]["estado"] == "bad"
    assert r["B"]["estado"] == "warn" and "mercado fechado" in r["B"]["palavra"]
    assert r["C"]["estado"] == "off" and "drenado" in r["C"]["palavra"]
    assert r["D"]["palavra"] == "com vetos"
    assert [x["id"] for x in A.carregar(AGORA, base)["slots"]][0] == "A", "o pior primeiro"
