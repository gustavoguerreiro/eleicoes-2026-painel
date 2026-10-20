"""Experimento 13: perfil 'governador' (o que vai ao ar no RN) contra um par REAL de governador do RN (2018: 1º -> 2º turno),
com a ordem de chegada REAL de 2026 do RN e três hipóteses para o viés de ordem DENTRO do município (-0.056 é o medido em 2026)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rn_2018 import feat, fin, instantaneo, mun_ok, ts, tot_apt, verdade  # noqa: E402
import projecao as pj  # noqa: E402

coef = pj.PERFIS["governador"]["coef"]
pri = {m: pj.prior_1t(t1u, 1.0 - t1u, 1.0, (0.0, 0.0, 0.0)) for m, t1u in ((m, 0.5) for m in mun_ok)}
pri = {m: pj.invlogit(coef[0] + coef[1] * pj.logit(feat[m]["u"]) + coef[2] * feat[m]["o"]) for m in mun_ok}
passos = ts[:: max(1, len(ts) // 60)]
print(f"verdade (Fátima entre os dois) {verdade:.3f}% | perfil governador: {pj.PERFIS['governador']}")
for desloc in (-0.056, 0.0, 0.05, -0.12):
    linhas = []
    for T in passos:
        us = instantaneo(T, desloc, None)
        frac = sum(u["apt_c"] for u in us) / tot_apt
        if not 0.10 <= frac <= 0.97:
            continue
        r = pj.projetar_com_faixa([dict(u, prior=pri[u["id"]]) for u in us], "governador")
        A = sum(u["a"] for u in us); B = sum(u["b"] for u in us)
        linhas.append((frac, r["pct_a"] - verdade, A / (A + B) * 100 - verdade, r["lo"] <= verdade <= r["hi"], r["hi"] - r["lo"]))
    def faixa(lo, hi, k):
        v = [l[k] for l in linhas if lo <= l[0] < hi]
        return math.sqrt(sum(x * x for x in v) / len(v)) if v else float("nan")
    cobre = sum(1 for l in linhas if l[3]) / len(linhas) * 100
    print(f"\nviés de ordem no município = {desloc:+.3f} logit ({'medido em 2026' if desloc == -0.056 else 'hipótese'}):  faixa contém a verdade em {cobre:.0f}% dos instantes")
    print(f"  {'apurado':>10s} {'placar':>8s} {'modelo':>8s} {'largura da faixa':>18s}")
    for lo, hi in ((0.10, 0.30), (0.30, 0.60), (0.60, 0.97)):
        lar = [l[4] for l in linhas if lo <= l[0] < hi]
        print(f"  {int(lo * 100):>3d}-{int(hi * 100):>3d}% {faixa(lo, hi, 2):8.2f} {faixa(lo, hi, 1):8.2f} {sum(lar) / len(lar):18.2f}")
