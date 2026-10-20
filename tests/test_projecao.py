"""Testes do modelo de projeção (backend/projecao.py) e da montagem das unidades no servidor. Rodam offline.
O teste de regressão com a noite real de 2022 só roda se `python modelo/dados_2022.py` e `modelo/dados_2022_municipios.py`
já tiverem gerado os dados em modelo/cache/ (são ~340 MB de download dos dados abertos do TSE)."""
import os
import sys
import unittest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "backend"))
sys.path.insert(0, os.path.join(AQUI, "..", "modelo"))

import projecao as pj  # noqa: E402
import painel_server as p  # noqa: E402


def unidade(i, a, b, apt_c, apt_t, prior=0.6, grupo="G"):
    return dict(id=i, grupo=grupo, a=a, b=b, apt_c=apt_c, apt_t=apt_t, prior=prior)


class NucleoDoModelo(unittest.TestCase):
    def test_apuracao_completa_devolve_o_resultado_exato(self):
        us = [unidade(i, 600 + 10 * i, 400, 1000, 1000, prior=0.5) for i in range(6)]
        r = pj.projetar(us)
        a, b = sum(u["a"] for u in us), sum(u["b"] for u in us)
        self.assertAlmostEqual(r["pct_a"], a / (a + b) * 100, places=9)
        self.assertEqual(r["faltam"], 0)

    def test_erro_de_nivel_do_prior_e_absorvido_pela_mare(self):
        base = [unidade(i, 300 + 7 * i, 200 + 3 * i, 600, 1500, prior=0.45 + 0.02 * i) for i in range(8)]
        r0 = pj.projetar(base, dict(psi=0.03))["pct_a"]
        for delta in (-0.4, 0.3):
            deslocado = [dict(u, prior=pj.invlogit(pj.logit(u["prior"]) + delta)) for u in base]
            self.assertAlmostEqual(pj.projetar(deslocado, dict(psi=0.03))["pct_a"], r0, places=6)

    def test_volume_que_falta_usa_os_votos_por_eleitor_da_propria_unidade(self):
        # 1.000 eleitores apurados deram 800 votos válidos; faltam 1.500 eleitores -> ~1.200 votos
        r = pj.projetar([unidade(1, 500, 300, 1000, 2500, prior=None)])
        self.assertAlmostEqual(r["faltam"], 1200, places=6)

    def test_sem_prior_cada_unidade_mantem_a_sua_fatia(self):
        us = [unidade(1, 800, 200, 500, 1000, prior=None), unidade(2, 200, 800, 1000, 1000, prior=None)]
        r = pj.projetar(us)
        # unidade 1: faltam 500 eleitores x 2 votos/eleitor = 1.000 votos, 80% para A
        self.assertAlmostEqual(r["a_final"], 800 + 800 + 200, places=6)

    def test_psi_positivo_favorece_a(self):
        us = [unidade(i, 400, 400, 400, 1600, prior=0.5) for i in range(5)]
        self.assertGreater(pj.projetar(us, dict(psi=0.1))["pct_a"], pj.projetar(us, dict(psi=0.0))["pct_a"])

    def test_confianca_na_propria_contagem_cresce_com_a_apuracao(self):
        # prior diz 50%, mas a unidade apurou 70%: com mais apuração, o que falta se aproxima dos 70%
        cedo = pj.projetar([unidade(1, 700, 300, 100, 1000, prior=0.5), unidade(2, 500, 500, 1000, 1000, prior=0.5)])
        tarde = pj.projetar([unidade(1, 700, 300, 900, 1000, prior=0.5), unidade(2, 500, 500, 1000, 1000, prior=0.5)])
        self.assertGreater(tarde["por_grupo"]["G"][0] / sum(tarde["por_grupo"]["G"]), cedo["por_grupo"]["G"][0] / sum(cedo["por_grupo"]["G"]) - 1)
        self.assertGreater(tarde["pct_a"], 0)

    def test_ponto_de_virada(self):
        atras, x = pj.ponto_virada(600, 400, 1000)
        self.assertEqual(atras, "b")
        self.assertAlmostEqual(x, 60.0)                         # b precisa de 60% dos 1.000 que faltam
        atras, x = pj.ponto_virada(300, 700, 100)
        self.assertEqual(atras, "a")
        self.assertGreater(x, 100)                              # não dá mais para virar
        self.assertIsNone(pj.ponto_virada(10, 20, 0)[1])


class FaixaEPerfis(unittest.TestCase):
    def amostra(self, frac):
        return [unidade(i, 600 * frac, 400 * frac, 1000 * frac, 1000, prior=0.6) for i in range(30)]

    def test_faixa_envolve_a_projecao_e_estreita_com_a_apuracao(self):
        larguras = []
        for frac in (0.2, 0.5, 0.9):
            r = pj.projetar_com_faixa(self.amostra(frac), "presidente")
            self.assertLessEqual(r["lo"], r["pct_a"])
            self.assertGreaterEqual(r["hi"], r["pct_a"])
            larguras.append(r["hi"] - r["lo"])
        self.assertGreater(larguras[0], larguras[1])
        self.assertGreater(larguras[1], larguras[2])

    def test_cedo_demais_nao_projeta(self):
        self.assertIsNone(pj.projetar_com_faixa(self.amostra(0.02), "presidente"))

    def test_decidido_quando_o_que_falta_nao_alcanca_a_diferenca(self):
        us = [unidade(i, 700 * 0.98, 300 * 0.98, 980, 1000, prior=0.7) for i in range(30)]
        r = pj.projetar_com_faixa(us, "presidente")
        self.assertTrue(r["decidido"])
        self.assertEqual(r["atras"], "b")

    def test_perfis_tem_os_parametros_calibrados(self):
        for nome, perfil in pj.PERFIS.items():
            for k in ("psi", "psi1", "psi2", "sigma_psi", "kw", "gamma", "coef"):
                self.assertIn(k, perfil, nome)
        self.assertGreater(pj.PERFIS["presidente"]["psi"], 0)      # o que falta é mais PT (2022)
        self.assertLess(pj.PERFIS["governador"]["psi"], 0.0)       # RN 2026: o que falta é menos PT


def arquivo(votos, te, est, vv=None, ts=100, st=50):
    """Mini-arquivo do TSE (-u.json) com os candidatos `votos` {numero: (sigla, votos)}."""
    vv = vv if vv is not None else sum(v for _, v in votos.values())
    cands = [dict(n=n, nm=f"CAND{n}", nmu=f"CAND{n}", vap=str(int(v)), pvap="0", dvt="Válido", e="n", st="") for n, (sg, v) in votos.items()]
    par = [dict(sg=sg, cand=[c]) for (n, (sg, _)), c in zip(votos.items(), cands)]
    return dict(s=dict(ts=str(ts), st=str(st), pst="50,00", pstn="50"), e=dict(te=str(te), est=str(est)), v=dict(vv=str(int(vv))),
                ht="20:00:00", carg=[dict(nv="1", agr=[dict(par=par)])])


class MontagemNoServidor(unittest.TestCase):
    def mundo(self, frac):
        d1, d2 = {}, {}
        for i, uf in enumerate(p.UFS + ["zz", "br"]):
            a1, b1, o1 = 5000 + 100 * i, 4000, 1000
            d1[(uf, 1)] = arquivo({"13": ("PT", a1), "22": ("PL", b1), "99": ("X", o1)}, te=20000, est=20000)
            d1[(uf, 1)]["carg"][0]["agr"][0]["par"][0]["cand"][0].update(e="s", st="2º turno")
            d1[(uf, 1)]["carg"][0]["agr"][0]["par"][1]["cand"][0].update(e="s", st="2º turno")
            d2[(uf, 1)] = arquivo({"13": ("PT", 6000 * frac), "22": ("PL", 5000 * frac)}, te=20000, est=int(20000 * frac))
        return d1, d2

    def test_projecao_brasil_identifica_os_lados_e_projeta(self):
        d1, d2 = self.mundo(0.6)
        r = p.projecao_brasil(d1, d2)
        self.assertIsNotNone(r)
        self.assertEqual((r["a"], r["b"]), ("13", "22"))           # A é o candidato do PT
        contado = 6000 / 11000 * 100
        self.assertGreater(r["pct_a"], contado)                    # o viés de ordem de 2022 empurra o que falta para o candidato A (PT)
        self.assertLess(r["pct_a"], contado + 2.0)
        self.assertLess(r["lo"], r["pct_a"])
        self.assertGreater(r["hi"], r["pct_a"])

    def test_projecao_brasil_sem_dados_do_2_turno_nao_projeta(self):
        d1, _ = self.mundo(0.6)
        self.assertIsNone(p.projecao_brasil(d1, {}))


@unittest.skipUnless(os.path.exists(os.path.join(AQUI, "..", "modelo", "cache", "2022_municipios.json")) and
                     os.path.exists(os.path.join(AQUI, "..", "modelo", "cache", "2022_2t_secoes.jsonl.gz")),
                     "dados de 2022 não baixados (python modelo/dados_2022.py)")
class NoiteDe2022(unittest.TestCase):
    """O modelo entregue (perfil 'presidente', com os coeficientes do perfil, sem ajuste nenhum em 2022) contra a ordem real da apuração."""

    def test_projecao_bate_com_o_resultado_final_e_ganha_do_placar(self):
        from nucleo import carregar_1t, instantaneos
        snaps, ap = instantaneos("uf", de=17 * 60 + 30, ate=20 * 60 + 40, passo=15)
        t1 = carregar_1t()
        verdade = ap.verdade() * 100
        coef = pj.PERFIS["presidente"]["coef"]
        prior = {}
        for uf, muns in t1.items():
            tot = {}
            for votos in muns.values():
                for k, v in votos.items():
                    tot[k] = tot.get(k, 0) + v
            val = sum(v for k, v in tot.items() if k not in ("95", "96"))
            prior[uf] = pj.prior_1t(tot.get("13", 0), tot.get("22", 0), val, coef)
        erros_modelo, erros_placar = [], []
        for m, pct, us in snaps:
            if not 0.15 <= pct < 0.99:
                continue
            r = pj.projetar_com_faixa([dict(u, grupo="BR", prior=prior.get(u["id"])) for u in us], "presidente")
            a = sum(u["a"] for u in us)
            b = sum(u["b"] for u in us)
            erros_modelo.append((pct, abs(r["pct_a"] - verdade), r["lo"] <= verdade <= r["hi"]))
            erros_placar.append(abs(a / (a + b) * 100 - verdade))
        self.assertTrue(erros_modelo)
        self.assertLess(max(e for p_, e, _ in erros_modelo if p_ >= 0.85), 0.15)
        self.assertLess(max(e for _, e, _ in erros_modelo), 0.5)
        self.assertTrue(all(ok for _, _, ok in erros_modelo), "a faixa precisa conter o resultado final em todos os instantes")
        self.assertLess(sum(e for _, e, _ in erros_modelo), sum(erros_placar) / 3)     # pelo menos 3x melhor que o placar


if __name__ == "__main__":
    unittest.main()
