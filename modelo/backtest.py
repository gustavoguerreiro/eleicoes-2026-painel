"""Backtest do modelo de projeção (backend/projecao.py) com a ordem REAL de chegada dos boletins do 2º turno de 2022.
Uso:  python modelo/backtest.py            # tabela comparativa e testes de robustez
Mede o erro (p.p.) na % final do Lula entre os dois finalistas, por faixa de apuração (% das seções recebidas)."""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nucleo import (ajusta_prior, avaliar, carregar_1t, features_1t, hhmm, instantaneos, priors, resumo)  # noqa: E402

snaps, ap = instantaneos("mun")
verdade = ap.verdade()
feat = features_1t(carregar_1t())
finais = ap.tot
UFS = sorted({k[0] for k in feat})
coef = {uf: ajusta_prior(feat, finais, uf) for uf in UFS}
coef["*"] = ajusta_prior(feat, finais, None)
print(f"verdade {verdade * 100:.3f}%  | prior (todos os estados): {[round(x, 3) for x in coef['*']]}")

FX = ((0.15, 0.50), (0.50, 0.85), (0.85, 0.99))
NOME = ["15-50%", "50-85%", "85-99%"]


def linha(rotulo, res):
    r = resumo(res, FX)
    print(f"{rotulo:46s} " + "  ".join(f"{NOME[i]}: rmse {r[i][0]:5.2f} máx {r[i][1]:5.2f}" for i in range(3)))


def rodar(rotulo, params, **kw):
    pri = priors(feat, coef, **kw)
    res = avaliar(snaps, pri, params, verdade)
    linha(rotulo, res)
    return res


print("\n=== referências (sem prior) ===")
from projecao import projetar  # noqa: E402
res = []
for m, pct, us in snaps:                         # M0: o placar do painel
    A = sum(u["a"] for u in us)
    B = sum(u["b"] for u in us)
    res.append((m, pct, (A / (A + B) - verdade) * 100))
linha("M0 placar (soma do que já foi apurado)", res)
rodar("M1m reponderado por município (sem prior)", {}, sem_prior=True)

print("\n=== com prior do 1º turno (maré + confiança na contagem) ===")
rodar("M3m psi=0", dict(psi=0.0))
for psi in (0.02, 0.03, 0.035, 0.04, 0.05):
    rodar(f"M3m psi={psi}", dict(psi=psi))

print("\n=== robustez: prior mal calibrado (nível, inclinação) com psi=0.035 ===")
for d in (-0.2, 0.2):
    rodar(f"nível do prior errado em {d:+.1f} logit", dict(psi=0.035), delta=d)
for b in (0.6, 0.8, 1.2):
    rodar(f"inclinação do prior x{b}", dict(psi=0.035), beta_fator=b)

print("\n=== ajuste fino (kw, gamma) com psi=0.035 ===")
for kw, g in itertools.product((500, 3000, 20000), (0.5, 1.0, 2.0)):
    rodar(f"kw={kw} gamma={g}", dict(psi=0.035, kw=kw, gamma=g))
