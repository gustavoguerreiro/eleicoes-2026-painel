"""Experimento 14 (RN, ordem real de 2026): o 1º turno de 2026 como TESTE FORA DA AMOSTRA do modelo calibrado em 2022.
Alvo: % do Lula entre Lula+Flávio no RN, 1º turno de 2026 (ordem real de chegada dos boletins de 2026).
Prior: só o 1º turno de 2022 em cada município (Lula x Bolsonaro; quatro anos antes). Unidades: os 167 municípios do RN.
Pergunta: os parâmetros de viés de ordem de 2022 funcionam numa eleição diferente (outro ano, outra rodada)?"""
import gzip
import json
import math
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nucleo import ajusta_prior, carregar_1t, features_1t, invlogit, logit  # noqa: E402
import projecao as pj  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
with gzip.open(os.path.join(AQUI, "cache", "rn_2026_1t_secoes.jsonl.gz"), "rt", encoding="utf-8") as f:
    ss = [json.loads(l) for l in f]
base = datetime(2026, 10, 4)
for s in ss:
    s["m"] = int((datetime.strptime(s["t"], "%Y-%m-%dT%H:%M:%S") - base).total_seconds() // 60)
    pv = s["v"].get("P", {})
    s["pl"], s["pf"] = pv.get("13", 0), pv.get("22", 0)
ss.sort(key=lambda s: s["m"])

fin = {}
for s in ss:
    f = fin.setdefault(s["mun"], dict(a=0, b=0, apt=0))
    f["a"] += s["pl"]; f["b"] += s["pf"]; f["apt"] += s["aptos"]

t22 = carregar_1t()["RN"]                                          # {municipio: {numero: votos}} do 1º turno de 2022
feat22 = {("RN", m): f for (u, m), f in features_1t({"RN": t22}).items()}
mun = [m for m in fin if ("RN", m) in feat22 and fin[m]["a"] + fin[m]["b"] > 50]
verdade = sum(fin[m]["a"] for m in mun) / sum(fin[m]["a"] + fin[m]["b"] for m in mun) * 100
coef = pj.PERFIS["presidente"]["coef"]
pri = {m: pj.prior_1t(t22[m].get("13", 0), t22[m].get("22", 0), sum(v for k, v in t22[m].items() if k not in ("95", "96")), coef) for m in mun}
num = den = 0.0
for m in mun:
    v = fin[m]["a"] + fin[m]["b"]
    num += v * (pri[m] - fin[m]["a"] / v) ** 2
    den += v
print(f"RN 2026 1º turno: Lula {verdade:.2f}% entre Lula+Flávio; {len(mun)} municípios; {len(ss)} seções")
print(f"o 1º turno de 2022 (4 anos antes) sozinho prevê cada município com erro de {math.sqrt(num / den) * 100:.2f} p.p. (ponderado)\n")

marcos = sorted({s["m"] for s in ss})
marcos = marcos[:: max(1, len(marcos) // 60)]
tot_apt = sum(fin[m]["apt"] for m in mun)
cur = {m: dict(a=0, b=0, apt=0) for m in mun}
snaps, i = [], 0
for T in marcos:
    while i < len(ss) and ss[i]["m"] <= T:
        s = ss[i]
        if s["mun"] in cur:
            c = cur[s["mun"]]
            c["a"] += s["pl"]; c["b"] += s["pf"]; c["apt"] += s["aptos"]
        i += 1
    us = [dict(id=m, grupo="RN", a=cur[m]["a"], b=cur[m]["b"], apt_c=cur[m]["apt"], apt_t=fin[m]["apt"], prior=pri[m]) for m in mun]
    snaps.append((sum(cur[m]["apt"] for m in mun) / tot_apt, us))

FX = [(0.10, 0.30), (0.30, 0.60), (0.60, 0.97)]


def rms(es, lo, hi):
    v = [e for p, e in es if lo <= p < hi]
    return math.sqrt(sum(x * x for x in v) / len(v)) if v else float("nan")


def rodar(par, usar_prior=True):
    out = []
    for p, us in snaps:
        if p < 0.05:
            continue
        r = pj.projetar([dict(u, prior=u["prior"] if usar_prior else None) for u in us], par)
        out.append((p, r["pct_a"] - verdade))
    return out


pl = []
for p, us in snaps:
    A = sum(u["a"] for u in us); B = sum(u["b"] for u in us)
    if A + B:
        pl.append((p, A / (A + B) * 100 - verdade))
print(f"{'modelo':58s} " + "  ".join(f"{int(lo * 100)}-{int(hi * 100)}%" for lo, hi in FX))
print(f"{'placar (sem modelo)':58s} " + "  ".join(f"{rms(pl, lo, hi):6.2f}" for lo, hi in FX))
print(f"{'reponderado por município (sem prior)':58s} " + "  ".join(f"{rms(rodar(dict(), False), lo, hi):6.2f}" for lo, hi in FX))
P = pj.PERFIS["presidente"]
for rot, par in [("prior de 2022, sem correção de ordem (psi=0)", dict()),
                 ("parâmetros de 2022 usados nos ESTADOS (psi .03, .05, .08)", dict(psi=P["psi"], psi1=P["psi1"], psi2=P["psi2"])),
                 ("parâmetros de 2022 usados nos MUNICÍPIOS (psi .035)", dict(psi=0.035)),
                 ("psi=0.07", dict(psi=0.07)), ("psi=0.10", dict(psi=0.10)), ("psi=-0.03", dict(psi=-0.03))]:
    es = rodar(par)
    print(f"{rot:58s} " + "  ".join(f"{rms(es, lo, hi):6.2f}" for lo, hi in FX))
melhor = min((sum(e * e for _, e in rodar(dict(psi=x / 100)) if 0.10 <= _ < 0.97), x / 100) for x in range(-10, 21, 1))
print(f"\nmelhor psi (municípios) para o RN em 2026: {melhor[1]:+.2f} (em 2022 foi +0.035)")
