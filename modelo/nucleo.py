"""Peças comuns do backtest: instantâneos da apuração de 2022, priors do 1º turno e avaliação de um conjunto de parâmetros."""
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(AQUI, "..", "backend"))
from projecao import invlogit, logit, projetar  # noqa: E402
from replay import Apuracao, carregar_1t, carregar_secoes, hhmm  # noqa: E402


def instantaneos(nivel="mun", de=17 * 60 + 10, ate=21 * 60 + 1, passo=10, ss=None):
    """[(minuto, fração de seções, unidades)] com o que o painel veria. Unidades ainda sem prior."""
    ss = ss or carregar_secoes()
    ap = Apuracao(ss, nivel)
    out = []
    for m in range(de, ate, passo):
        ap.avancar(m)
        us = []
        for u in ap.unidades():
            k = u["id"]
            grupo = k if nivel == "uf" else k[0]
            us.append(dict(id=k, grupo=grupo, a=u["a"], b=u["b"], apt_c=u["apt_c"], apt_t=u["apt_t"]))
        out.append((m, ap.pct_secoes, us))
    return out, ap


def features_1t(t1):
    f = {}
    for uf, muns in t1.items():
        for mun, votos in muns.items():
            l, b = votos.get("13", 0), votos.get("22", 0)
            val = sum(v for k, v in votos.items() if k not in ("95", "96"))
            if l + b > 0 and val > 0:
                f[(uf, mun)] = dict(u=l / (l + b), o=1 - (l + b) / val)
    return f


def _resolve(A, B):
    n = len(B)
    M = [row[:] + [B[i]] for i, row in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [x - f * y for x, y in zip(M[r], M[i])]
    return [M[i][n] / M[i][i] for i in range(n)]


def ajusta_prior(feat, finais, excluir_uf=None):
    """logit(y) = a + b*logit(u) + c*o, por mínimos quadrados ponderados pelos votos do 2º turno (sem o estado excluído)."""
    X, Y, W = [], [], []
    for k, f in feat.items():
        if k[0] == excluir_uf or k not in finais:
            continue
        a, b = finais[k]["a"], finais[k]["b"]
        if a + b < 50:
            continue
        X.append((1.0, logit(f["u"]), f["o"]))
        Y.append(logit(a / (a + b)))
        W.append(a + b)
    A = [[sum(w * x[i] * x[j] for x, w in zip(X, W)) for j in range(3)] for i in range(3)]
    B = [sum(w * x[i] * y for x, y, w in zip(X, Y, W)) for i in range(3)]
    return _resolve(A, B)


def priors(feat, coef_por_uf, beta_fator=1.0, delta=0.0, sem_prior=False):
    """{(uf, mun): probabilidade de A entre A+B}. beta_fator e delta simulam um prior mal calibrado."""
    if sem_prior:
        return {}
    out = {}
    for k, f in feat.items():
        c = coef_por_uf.get(k[0]) or coef_por_uf["*"]
        out[k] = invlogit(c[0] + beta_fator * c[1] * logit(f["u"]) + c[2] * f["o"] + delta)
    return out


def avaliar(snaps, pri, params, verdade, nivel="mun"):
    """Lista de (minuto, fração de seções, erro em p.p.)."""
    res = []
    for m, pct, us in snaps:
        com = [dict(u, prior=pri.get(u["id"] if nivel == "mun" else None)) for u in us]
        r = projetar(com, params)
        res.append((m, pct, r["pct_a"] - verdade * 100))
    return res


def resumo(res, faixas=((0.15, 0.50), (0.50, 0.85), (0.85, 0.99))):
    out = []
    for lo, hi in faixas:
        es = [e for _, p, e in res if lo <= p < hi]
        out.append((math.sqrt(sum(e * e for e in es) / len(es)) if es else float("nan"), max((abs(e) for e in es), default=float("nan"))))
    return out
