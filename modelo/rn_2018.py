"""Dados e instantâneo para os experimentos 9 e 13 (RN): backtest REALISTA do governador. Resultado verdadeiro = RN 2018 (Fátima/PT x Carlos Eduardo), um par real
de 1º e 2º turno de governador. Ordem de apuração = o perfil de chegada dos boletins de CADA município no 1º turno de 2026
(dentro do município, a ordem é sorteada; opcionalmente soma-se um deslocamento de ordem em logit)."""
import gzip
import json
import math
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nucleo import ajusta_prior, invlogit, logit, projetar  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(AQUI, "cache", "rn_2018_municipios.json"), encoding="utf-8"))
t1, t2 = d["1"], d["2"]
feat, fin = {}, {}
for m, v in t1.items():
    a, b = v.get("13", 0), v.get("12", 0)
    val = sum(x for k, x in v.items() if k not in ("95", "96"))
    if a + b > 0 and val > 0 and m in t2 and t2[m].get("13", 0) + t2[m].get("12", 0) > 0:
        feat[m] = dict(u=a / (a + b), o=1 - (a + b) / val)
        fin[m] = dict(a=t2[m].get("13", 0), b=t2[m].get("12", 0))
verdade = sum(x["a"] for x in fin.values()) / sum(x["a"] + x["b"] for x in fin.values()) * 100

# perfil de chegada por município (2026): lista de (minuto, aptos) ordenada
with gzip.open(os.path.join(AQUI, "cache", "rn_2026_1t_secoes.jsonl.gz"), "rt", encoding="utf-8") as f:
    s26 = [json.loads(l) for l in f]
base = datetime(2026, 10, 4)
perfil = {}
for s in s26:
    perfil.setdefault(s["mun"], []).append((int((datetime.strptime(s["t"], "%Y-%m-%dT%H:%M:%S") - base).total_seconds() // 60), s["aptos"]))
for m in perfil:
    perfil[m].sort()
mun_ok = [m for m in feat if m in perfil]
apt_t = {m: sum(x[1] for x in perfil[m]) for m in mun_ok}
ts = sorted(t for m in mun_ok for t, _ in perfil[m])
tot_apt = sum(apt_t.values())


def frac(m, T):
    return sum(a for t, a in perfil[m] if t <= T) / apt_t[m]


COEF = {
    "uniforme (inclinação 1, outros 0)": [0.0, 1.0, 0.0],
    "ajustado em 2018 (otimista)": ajusta_prior({("RN", m): feat[m] for m in mun_ok}, {("RN", m): fin[m] for m in mun_ok}, None),
}
COEF["meio-termo (inclinação .85, outros -.8)"] = [0.0, 0.85, -0.8]


def instantaneo(T, desloc, sorteio):
    us = []
    for m in mun_ok:
        p = frac(m, T)
        a, b = fin[m]["a"], fin[m]["b"]
        v = a + b
        s = a / v
        # parte já apurada: p do município, com o deslocamento de ordem (a parte apurada é MENOS "A" por `desloc` logit)
        ca = logit(s) - desloc * (1 - p)
        sc = invlogit(ca)
        ap = p * v
        us.append(dict(id=m, grupo="RN", a=ap * sc, b=ap * (1 - sc), apt_c=p * apt_t[m], apt_t=apt_t[m]))
    return us


def rodar(coef_nome, par, desloc, passos):
    c = COEF[coef_nome]
    pri = {m: invlogit(c[0] + c[1] * logit(feat[m]["u"]) + c[2] * feat[m]["o"]) for m in mun_ok}
    erros = []
    for T in passos:
        us = instantaneo(T, desloc, None)
        ap = sum(u["apt_c"] for u in us) / tot_apt
        if ap < 0.10 or ap > 0.97:
            continue
        r = projetar([dict(u, prior=pri[u["id"]]) for u in us], par)
        A = sum(u["a"] for u in us)
        B = sum(u["b"] for u in us)
        erros.append((ap, r["pct_a"] - verdade, A / (A + B) * 100 - verdade))
    return erros


