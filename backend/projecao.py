"""Projeção do resultado final de um 2º turno a partir da apuração parcial. Só biblioteca padrão.

Ideia (resumida; o guia completo está em modelo/README.md):
  1. Quanto falta: o eleitorado ainda não apurado de cada unidade (município ou estado) x os votos válidos por eleitor que a
     própria unidade já mostrou. (Em 2022 isso acertou o volume restante com ~1% de erro em qualquer ponto da apuração.)
  2. Quem leva o que falta: cada unidade tem um PRIOR (probabilidade do candidato A entre A+B prevista só pelo 1º turno).
     O que já foi apurado mostra o quanto o 2º turno está deslocado do prior: a MARÉ (média, em logit, ponderada pelos
     votos), encolhida do estado para o país. A unidade confia cada vez mais na sua própria contagem (peso = fração apurada).
  3. Correção de ordem: as seções que chegam por último tendem a ser mais favoráveis a um dos lados que as primeiras. O
     parâmetro `psi` (logit, positivo = favorece A) corrige isso e vem do backtest com a ordem real de 2022.

Convenções: A e B são os dois finalistas; "a" e "b" são os votos de cada um já apurados; share = a / (a + b)."""
import math

PARAMS = dict(
    kw=3000.0,         # peso (votos) a partir do qual a maré do estado vale mais que a nacional
    gamma=1.0,         # confiança na contagem da própria unidade: kappa = fracao_apurada ** gamma
    psi=0.0,           # correção de ordem (logit) aplicada ao que falta; positivo favorece A
    psi1=0.0,          # o que falta é mais "extremo" que o contado: soma psi1 * logit(prior) (amplifica o lado dominante)
    psi2=0.0,          # o viés das últimas seções cresce com a fração já apurada da unidade: soma psi2 * fração_apurada
    apt_min=150,       # eleitores apurados mínimos para usar a taxa de votos válidos da própria unidade
    votos_min=30,      # votos válidos (A+B) mínimos para a unidade contribuir com a maré
)


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def invlogit(x):
    return 1.0 / (1.0 + math.exp(-x))


def _taxas(unidades):
    """Votos válidos (A+B) por eleitor apurado: do país e de cada grupo (estado)."""
    nac, por = [0.0, 0.0], {}
    for u in unidades:
        v, e = u["a"] + u["b"], u["apt_c"]
        nac[0] += v
        nac[1] += e
        g = por.setdefault(u["grupo"], [0.0, 0.0])
        g[0] += v
        g[1] += e
    rho_nac = nac[0] / nac[1] if nac[1] > 0 else 0.0
    rho_g = {k: (v[0] / v[1] if v[1] > 500 else rho_nac) for k, v in por.items()}
    return rho_nac, rho_g


def projetar(unidades, params=None):
    """unidades: lista de dict(id, grupo, a, b, apt_c, apt_t, prior).
    `prior`: probabilidade de A entre A+B prevista só pelo 1º turno (ou None se a unidade não tem 1º turno).
    Devolve dict(pct_a, a_final, b_final, faltam, mare, a_atual, b_atual, frac_apurada)."""
    P = dict(PARAMS, **(params or {}))
    rho_nac, rho_g = _taxas(unidades)
    linhas = []
    for u in unidades:
        a, b, apt_c, apt_t = u["a"], u["b"], u["apt_c"], u["apt_t"]
        rho = (a + b) / apt_c if apt_c >= P["apt_min"] else rho_g.get(u["grupo"], rho_nac)
        n = max(0.0, rho * (apt_t - apt_c))
        linhas.append((u, a, b, apt_c, apt_t, n))

    # maré: desvio médio (logit) entre o que cada unidade já mostrou e o seu prior, ponderado pelos votos
    r, w_g, s_g, w_n, s_n = {}, {}, {}, 0.0, 0.0
    for u, a, b, apt_c, apt_t, n in linhas:
        pi = u.get("prior")
        if pi is None or a + b < P["votos_min"]:
            continue
        rm = logit(a / (a + b)) - logit(pi)
        w = a + b
        r[id(u)] = rm
        w_g[u["grupo"]] = w_g.get(u["grupo"], 0.0) + w
        s_g[u["grupo"]] = s_g.get(u["grupo"], 0.0) + w * rm
        w_n += w
        s_n += w * rm
    th_n = s_n / w_n if w_n else 0.0
    th_g = {g: (s_g[g] + P["kw"] * th_n) / (w_g[g] + P["kw"]) for g in w_g}

    A = B = 0.0
    faltam = 0.0
    por_grupo = {}
    for u, a, b, apt_c, apt_t, n in linhas:
        pi = u.get("prior")
        if pi is None:
            q = a / (a + b) if a + b > 0 else 0.5
        else:
            th = th_g.get(u["grupo"], th_n)
            dev, kap = 0.0, 0.0
            frac_u = min(1.0, apt_c / apt_t) if apt_t > 0 else 1.0
            if id(u) in r and apt_t > 0:
                kap = frac_u ** P["gamma"]
                dev = r[id(u)] - th
            q = invlogit(logit(pi) + th + kap * dev + P["psi"] + P["psi1"] * logit(pi) + P["psi2"] * frac_u)
        A += a + n * q
        B += b + n * (1 - q)
        faltam += n
        g = por_grupo.setdefault(u["grupo"], [0.0, 0.0])
        g[0] += a + n * q
        g[1] += b + n * (1 - q)
    a_at = sum(x[1] for x in linhas)
    b_at = sum(x[2] for x in linhas)
    apt_c_t = sum(x[3] for x in linhas)
    apt_t_t = sum(x[4] for x in linhas)
    return dict(pct_a=(A / (A + B) * 100 if A + B > 0 else None), a_final=A, b_final=B, faltam=faltam, mare=th_n,
                a_atual=a_at, b_atual=b_at, frac_apurada=(apt_c_t / apt_t_t if apt_t_t else 0.0), por_grupo=por_grupo)


def ponto_virada(a, b, faltam):
    """Quanto do que falta (% dos votos válidos restantes) o candidato que está ATRÁS precisa para virar.
    Sem nenhuma suposição sobre quem leva o que falta. > 100: decidido. Devolve (atras, pct_necessario)."""
    if faltam <= 0:
        return ("a" if a < b else "b", None)
    atras, lider_v, atras_v = ("a", b, a) if a < b else ("b", a, b)
    x = (lider_v - atras_v + faltam) / (2.0 * faltam) * 100.0
    return (atras, x)


# ---- perfis calibrados no backtest (modelo/README.md) ------------------------------------------------------------------
#   presidente: unidades = estados (+ exterior). psi e psi1 vêm da noite de 2022 (2º turno, ordem real dos boletins).
#   governador: unidades = municípios do estado. psi vem do 1º turno de 2026 no RN (ordem real, mesmos candidatos): o que falta é
#               um pouco MENOS "A" (candidato do PT) que o já apurado. Incerteza maior, porque o 1º turno prevê pior o governador.
# `coef` = (intercepto, inclinação do 1º turno, peso dos "outros candidatos"): o intercepto não importa (a maré o recalcula).
# `sigma_psi` = incerteza (logit) na transferência desse viés de ordem para a eleição de agora; a faixa é a projeção com psi ± sigma.
PERFIS = {
    "presidente": dict(psi=0.03, psi1=0.05, psi2=0.08, sigma_psi=0.05, kw=3000.0, gamma=1.0, coef=(0.0, 0.975, -0.023),
                       conf_media=0.25, conf_alta=0.60),
    "governador": dict(psi=-0.04, psi1=0.0, psi2=0.0, sigma_psi=0.08, kw=3000.0, gamma=1.0, coef=(0.0, 0.85, -0.8),
                       conf_media=0.50, conf_alta=0.85),
}
MIN_APURADO = 0.05          # abaixo disso o painel diz "ainda cedo para projetar"


def prior_1t(a1, b1, validos1, coef):
    """Probabilidade de A entre A+B prevista só pelo 1º turno (a1, b1 = votos dos finalistas; validos1 = todos os válidos)."""
    if a1 <= 0 or b1 <= 0 or validos1 <= 0:
        return None
    return invlogit(coef[0] + coef[1] * logit(a1 / (a1 + b1)) + coef[2] * (1.0 - (a1 + b1) / validos1))


def projetar_com_faixa(unidades, perfil):
    """Projeção + faixa de cenários + ponto de virada. `perfil`: chave de PERFIS. Devolve None se for cedo demais."""
    P = PERFIS[perfil]
    base = {k: P[k] for k in ("psi", "psi1", "psi2", "kw", "gamma")}
    r = projetar(unidades, base)
    if r["pct_a"] is None or r["frac_apurada"] < MIN_APURADO or r["a_atual"] + r["b_atual"] <= 0:
        return None
    s = P["sigma_psi"]
    lo = projetar(unidades, dict(base, psi=P["psi"] - s))["pct_a"]
    hi = projetar(unidades, dict(base, psi=P["psi"] + s))["pct_a"]
    falta = 1.0 - r["frac_apurada"]
    folga = 0.02 + 0.06 * falta                          # ruído que o modelo não captura (município a município)
    lo, hi = min(lo, hi, r["pct_a"]) - folga, max(lo, hi, r["pct_a"]) + folga
    atras, virada = ponto_virada(r["a_atual"], r["b_atual"], r["faltam"])
    return dict(pct_a=r["pct_a"], lo=max(0.0, lo), hi=min(100.0, hi), faltam=r["faltam"], frac_apurada=r["frac_apurada"],
                atras=atras, virada=virada, decidido=bool(virada is not None and virada > 105.0),
                confianca="baixa" if r["frac_apurada"] < P["conf_media"] else "média" if r["frac_apurada"] < P["conf_alta"] else "alta")
