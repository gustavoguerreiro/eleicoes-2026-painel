"""Testes do núcleo do painel (coleta do TSE, estado do 2º turno, situação do duelo, histórico e cache). Rodam offline."""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import painel_server as p  # noqa: E402
from chat import Limitador  # noqa: E402
import chat as chat_mod  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "fixtures", "pres_2t_zerado.json"), encoding="utf-8") as f:
    ZERADO = json.load(f)      # arquivo real do TSE publicado dias antes do 2º turno: candidatos sem `dvt`, tudo zerado


def parcial(pct_apurado, votos_a, votos_b, **extra):
    """O mesmo arquivo, com apuração em andamento. A = Flávio, B = Lula; como o TSE, já traz `dvt` nos candidatos."""
    j = copy.deepcopy(ZERADO)
    j["s"].update(pst=f"{pct_apurado:.2f}".replace(".", ","), pstn=str(pct_apurado).replace(".", ","))
    total = votos_a + votos_b
    j["v"].update(vv=str(total), vvc=str(total))
    j["ht"] = "20:15:00"
    vot = {"22": votos_a, "13": votos_b}
    for cg in j["carg"]:
        for ag in cg["agr"]:
            for pa in ag["par"]:
                for c in pa["cand"]:
                    v = vot[str(c["n"])]
                    c.update(vap=str(v), pvap=f"{v / total * 100:.2f}".replace(".", ","), dvt="Válido", **extra)
    return j


class ArquivoZerado(unittest.TestCase):
    def test_candidatos_do_arquivo_zerado_valem_como_validos(self):
        cs = p.candidatos(ZERADO)
        self.assertEqual({c["n"] for c in cs}, {"22", "13"})
        self.assertTrue(all(c["valido"] and c["votos"] == 0 for c in cs))

    def test_apurado_zero_e_arquivo_sem_secoes(self):
        self.assertEqual(p.apurado(ZERADO), 0)
        self.assertEqual(p.apurado({}), 0)

    def test_situacao_aguarda_apuracao(self):
        s = p.situacao_2t(ZERADO, [c for c in p.candidatos(ZERADO)])
        self.assertEqual(s["rotulo"], "AGUARDANDO APURAÇÃO")

    def test_web_2t_zerado_cai_para_o_desempenho_do_1_turno(self):
        j1 = parcial(100, 56_104_503, 53_879_538)            # só serve de "1º turno" com dois candidatos
        d = p.web_2t(ZERADO, j1)
        self.assertFalse(d["ao_vivo"])
        self.assertEqual(d["apur"], 0)
        self.assertEqual(len(d["cands"]), 2)


class EstadoAoVivo(unittest.TestCase):
    def setUp(self):
        p._AO_VIVO["v"] = False
        p.CACHE_URL.clear()
        self._cod = unittest.mock.patch.object(p, "codigos_turno", return_value=dict(pres1="6257", pres2="6258", dem1="6259", dem2="6260"))
        self._cod.start()
        self.addCleanup(self._cod.stop)
        self.addCleanup(lambda: p._AO_VIVO.update(v=False))

    def test_arquivo_zerado_nao_conta_como_2_turno(self):
        with unittest.mock.patch.object(p, "baixar_cache", return_value=ZERADO):
            self.assertFalse(p.t2_disponivel())

    def test_vira_ao_vivo_e_nao_volta_atras_com_falha_do_tse(self):
        with unittest.mock.patch.object(p, "baixar_cache", return_value=parcial(5, 600, 550)):
            self.assertTrue(p.t2_disponivel())
        with unittest.mock.patch.object(p, "baixar_cache", return_value=None):          # TSE caiu / 429 no meio da contagem
            self.assertTrue(p.t2_disponivel())

    def test_meta_expoe_horario_de_inicio(self):
        with unittest.mock.patch.object(p, "baixar_cache", return_value=None):
            m = p.meta()
        self.assertFalse(m["t2_disponivel"])
        self.assertTrue(m["inicio_2t"].startswith("2026-10-25T19:00"))


class SituacaoDoDuelo(unittest.TestCase):
    def sit(self, apur, a, b, **extra):
        j = parcial(apur, a, b, **extra)
        return p.situacao_2t(j, [c for c in p.candidatos(j) if c["valido"]])

    def test_disputa_aberta_no_comeco(self):
        s = self.sit(5, 600_000, 400_000)                     # líder com 20 p.p. de vantagem, mas só 5% apurado
        self.assertEqual(s["rotulo"], "DISPUTA ABERTA")

    def test_vitoria_projetada_exige_folga_e_30_por_cento_apurado(self):
        self.assertEqual(self.sit(80, 900_000, 100_000)["rotulo"], "VITÓRIA PROJETADA")
        # 90% apurado, vantagem de 1 p.p.: o que falta (~11% dos votos) é maior que a diferença
        self.assertEqual(self.sit(90, 505_000, 495_000)["rotulo"], "DISPUTA ABERTA")

    def test_margem_de_seguranca_sobre_o_que_falta(self):
        # 60% apurado: faltam ~66,7% de 1.000.000 = 666.667. Diferença de 700.000 passa por pouco, mas sem a folga de 30% não passa
        s = self.sit(60, 850_000, 150_000)
        self.assertEqual(s["rotulo"], "DISPUTA ABERTA")

    def test_eleito_so_quando_o_tse_marca(self):
        s = self.sit(100, 600_000, 400_000, e="s", st="Eleito")
        self.assertEqual(s["rotulo"], "ELEITO")


class ColetaDoTse(unittest.TestCase):
    def setUp(self):
        p.CACHE_URL.clear()
        p.CACHE_TTL = 15
        self.addCleanup(lambda: p.CACHE_URL.clear())
        self.addCleanup(lambda: setattr(p, "CACHE_TTL", 0))

    def test_falha_passageira_devolve_o_ultimo_dado_bom(self):
        url = "https://exemplo/x.json"
        with unittest.mock.patch.object(p, "_requisitar", return_value=(200, {"a": 1}, '"v1"')):
            self.assertEqual(p.baixar_cache(url), {"a": 1})
        p.CACHE_URL[url]["t"] -= 100                                        # expira
        with unittest.mock.patch.object(p, "_requisitar", return_value=(0, None, None)):
            self.assertEqual(p.baixar_cache(url), {"a": 1})                   # NÃO vira "sem dados"

    def test_304_reaproveita_o_que_ja_temos_e_envia_etag(self):
        url = "https://exemplo/y.json"
        with unittest.mock.patch.object(p, "_requisitar", return_value=(200, {"b": 2}, '"v1"')):
            p.baixar_cache(url)
        p.CACHE_URL[url]["t"] -= 100
        with unittest.mock.patch.object(p, "_requisitar", return_value=(304, None, '"v1"')) as req:
            self.assertEqual(p.baixar_cache(url), {"b": 2})
        req.assert_called_once_with(url, '"v1"')

    def test_404_e_ausencia_de_dados(self):
        with unittest.mock.patch.object(p, "_requisitar", return_value=(404, None, None)):
            self.assertIsNone(p.baixar_cache("https://exemplo/z.json"))

    def test_sem_cache_e_com_falha_devolve_none(self):
        with unittest.mock.patch.object(p, "_requisitar", return_value=(0, None, None)):
            self.assertIsNone(p.baixar_cache("https://exemplo/w.json"))


class HistoricoDoDuelo(unittest.TestCase):
    def test_registra_so_quando_muda_e_ignora_zerado(self):
        h = p.Historico()
        h.registrar("BR", ZERADO)
        self.assertEqual(h.serie("BR"), [])
        h.registrar("BR", parcial(10, 600, 400))
        h.registrar("BR", parcial(10, 600, 400))                  # igual: não duplica
        h.registrar("BR", parcial(20, 1300, 900))
        s = h.serie("BR")
        self.assertEqual([x["a"] for x in s], [10, 20])
        self.assertEqual(s[1]["v"], {"22": 1300, "13": 900})

    def test_sobrevive_a_reinicio(self):
        with tempfile.TemporaryDirectory() as d:
            arq = os.path.join(d, "h.json")
            p.Historico(arq).registrar("RN", parcial(10, 600, 400))
            self.assertEqual(len(p.Historico(arq).serie("RN")), 1)

    def test_limita_o_tamanho(self):
        h = p.Historico(maximo=3)
        for i in range(1, 8):
            h.registrar("BR", parcial(i, 100 * i, 90 * i))
        self.assertEqual([x["a"] for x in h.serie("BR")], [5, 6, 7])


class CacheVivoTeste(unittest.TestCase):
    def test_mantem_o_ultimo_dado_se_a_renovacao_falha(self):
        c = p.CacheVivo(intervalo=0.01)
        estado = {"n": 0}

        def fn():
            estado["n"] += 1
            if estado["n"] > 1:
                raise RuntimeError("TSE fora")
            return b"bom"
        self.assertEqual(c.obter("k", fn).js, b"bom")
        time.sleep(0.05)
        item = c.itens["k"]
        with self.assertLogs("painel", "ERROR"):
            c._renovar(item, "k")                                 # renovação falha
        self.assertEqual(c.obter("k", fn).js, b"bom")

    def test_primeira_chamada_busca_uma_vez_so(self):
        c = p.CacheVivo(intervalo=60)
        chamadas = []

        def fn():
            chamadas.append(1)
            time.sleep(0.1)
            return b"x"
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(4) as ex:
            res = [r.js for r in ex.map(lambda _: c.obter("k", fn), range(4))]
        self.assertEqual(res, [b"x"] * 4)
        self.assertEqual(len(chamadas), 1)


class LimiteDoChat(unittest.TestCase):
    def test_teto_global_por_dia(self):
        with unittest.mock.patch.object(chat_mod, "LIMITE_GLOBAL_DIA", 3), unittest.mock.patch.object(chat_mod, "LIMITE_JANELA", (99, 600)):
            lim = Limitador()
            for i in range(3):
                self.assertTrue(lim.permitir(f"ip{i}")[0])
            ok, msg = lim.permitir("outro")
            self.assertFalse(ok)
            self.assertIn("hoje", msg)


class ColdStart(unittest.TestCase):
    def test_falha_na_primeira_busca_nao_refaz_a_cada_requisicao(self):
        c = p.CacheVivo(intervalo=60)
        chamadas = []

        def fn():
            chamadas.append(1)
            raise RuntimeError("TSE fora")
        with self.assertLogs("painel", "ERROR"):
            self.assertIsNone(c.obter("k", fn))
        for _ in range(5):                                          # as seguintes respondem na hora (503), sem nova busca
            self.assertIsNone(c.obter("k", fn))
        self.assertEqual(len(chamadas), 1)

    def test_chaves_fixas_alimentam_o_health(self):
        c = p.CacheVivo(intervalo=60)
        self.assertIsNone(c.idade_fixos())
        c.registrar("k", lambda: b"x", fixo=True)
        c.obter("k", lambda: b"x")
        self.assertLess(c.idade_fixos(), 5)


class SegurancaDoChat(unittest.TestCase):
    def test_rebinding_nao_passa(self):
        ok = p.hosts_permitidos("127.0.0.1", 8765)
        self.assertTrue(p.origem_permitida("http://localhost:8765", "localhost:8765", ok))
        self.assertFalse(p.origem_permitida("http://evil.com", "localhost:8765", ok))            # outro site
        self.assertFalse(p.origem_permitida("http://evil.com:8765", "evil.com:8765", ok))         # rebinding: Origin == Host
        self.assertFalse(p.origem_permitida(None, "localhost:8765", ok))                          # sem Origin

    def test_producao_aceita_o_dominio_configurado(self):
        extras = {"https://painel.exemplo.com"}
        ok = p.hosts_permitidos("0.0.0.0", 8765, extras)
        self.assertTrue(p.origem_permitida("https://painel.exemplo.com", "painel.exemplo.com", ok, extras))
        self.assertFalse(p.origem_permitida("http://evil.com", "evil.com", ok, extras))

    def test_publico_sem_lista_aceita_mesmo_host(self):
        ok = p.hosts_permitidos("0.0.0.0", 8765)
        self.assertIsNone(ok)
        self.assertTrue(p.origem_permitida("https://meu.site", "meu.site", ok))
        self.assertFalse(p.origem_permitida("https://outro.site", "meu.site", ok))

    def test_ip_do_cliente(self):
        h = {"CF-Connecting-IP": "1.1.1.1", "X-Forwarded-For": "9.9.9.9, 2.2.2.2"}
        self.assertEqual(p.ip_cliente(h, "10.0.0.1", False), "10.0.0.1")                          # sem proxy: ignora cabeçalhos
        self.assertEqual(p.ip_cliente(h, "10.0.0.1", True), "1.1.1.1")
        self.assertEqual(p.ip_cliente({"X-Forwarded-For": "9.9.9.9, 2.2.2.2"}, "10.0.0.1", True), "2.2.2.2")


class ServidorHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading
        cls.patches = [unittest.mock.patch.object(p, "dados_2t", side_effect=lambda uf: {"turno": 2, "texto": "x" * 3000}),
                       unittest.mock.patch.object(p, "dados_web", side_effect=lambda *a: {"turno": 1}),
                       unittest.mock.patch.object(p, "mapa_municipios", side_effect=lambda *a: {"municipios": {}})]
        for x in cls.patches:
            x.start()
        cls.s = p.criar_servidor("127.0.0.1", 0, "rn", False, False, 15)
        cls.porta = cls.s.srv.server_address[1]
        threading.Thread(target=cls.s.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.srv.shutdown()
        cls.s.srv.server_close()
        for x in cls.patches:
            x.stop()

    def req(self, metodo, caminho, corpo=None, **cab):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        c.request(metodo, caminho, corpo, cab)
        r = c.getresponse()
        dados = r.read()
        return r, dados

    def test_api_cache_etag_304_e_gzip(self):
        r, dados = self.req("GET", "/api?uf=rn&turno=2")
        self.assertEqual(r.status, 200)
        self.assertIn("s-maxage", r.getheader("Cache-Control"))
        tag = r.getheader("ETag")
        self.assertEqual(json.loads(dados)["turno"], 2)
        r2, _ = self.req("GET", "/api?uf=rn&turno=2", **{"If-None-Match": tag})
        self.assertEqual(r2.status, 304)
        r3, gz = self.req("GET", "/api?uf=rn&turno=2", **{"Accept-Encoding": "gzip"})
        self.assertEqual(r3.getheader("Content-Encoding"), "gzip")
        import gzip
        self.assertEqual(json.loads(gzip.decompress(gz))["turno"], 2)

    def test_rotas_desconhecidas_dao_404(self):
        self.assertEqual(self.req("GET", "/apiXYZ")[0].status, 404)
        self.assertEqual(self.req("GET", "/qualquer")[0].status, 404)

    def test_pagina_e_healthz(self):
        r, html = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Apura", html)
        self.assertIn("default-src", r.getheader("Content-Security-Policy"))
        self.assertEqual(self.req("GET", "/healthz")[0].status, 200)

    def test_chat_recusa_origem_de_fora_e_rebinding(self):
        cab = {"Content-Type": "application/json"}
        self.assertEqual(self.req("POST", "/api/chat", "{}", Origin="http://evil.com", **cab)[0].status, 403)
        self.assertEqual(self.req("POST", "/api/chat", "{}", Origin="http://evil.com", Host="evil.com", **cab)[0].status, 403)
        self.assertEqual(self.req("POST", "/api/chat", "{}", **cab)[0].status, 403)                 # sem Origin

    def test_chat_aceita_a_propria_pagina(self):
        cab = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.porta}"}
        r, _ = self.req("POST", "/api/chat", json.dumps({"mensagem": "oi"}), **cab)
        self.assertEqual(r.status, 200)


class SimuladorDoSegundoTurno(unittest.TestCase):
    """O relógio simulado vai de 17h a 22h; os testes fixam o minuto em vez de esperar."""

    def setUp(self):
        self.j1 = parcial(100, 600_000, 450_000)
        self.fim = lambda: None
        patches = [unittest.mock.patch.object(p, "_1t_fixo", return_value=self.j1),
                   unittest.mock.patch.object(p, "codigos_turno",
                                              return_value=dict(pres1="6257", pres2="6258", dem1="6259", dem2="6260"))]
        for x in patches:
            x.start()
            self.addCleanup(x.stop)

    def estado(self, hora, minuto=0):
        with unittest.mock.patch.object(p, "minuto_sim", return_value=float(hora * 60 + minuto)):
            return p.sintetizar_2t(self.j1, "https://tse/6258/dados/rn/rn-c0001-e006258-u.json")

    def brasil(self, hora, minuto=0):
        with unittest.mock.patch.object(p, "minuto_sim", return_value=float(hora * 60 + minuto)):
            return p.sintetizar_br(self.j1)

    def votos(self, j):
        return {c["n"]: c["votos"] for c in p.candidatos(j)}

    def test_zerado_ate_as_19h(self):
        for j in (self.estado(17), self.estado(18, 59), self.brasil(18, 30)):
            self.assertEqual(p.apurado(j), 0)
            self.assertEqual(sum(self.votos(j).values()), 0)

    def test_a_contagem_so_acumula_e_termina_em_100(self):
        ant, ant_ap = {"22": 0, "13": 0}, 0.0
        for minuto in range(19 * 60, 22 * 60 + 1, 5):
            j = self.estado(minuto // 60, minuto % 60)
            v, ap = self.votos(j), p.apurado(j)
            self.assertTrue(all(v[n] >= ant[n] for n in v), f"votos diminuíram às {minuto // 60}:{minuto % 60:02d}")
            self.assertGreaterEqual(ap, ant_ap)
            ant, ant_ap = v, ap
        self.assertAlmostEqual(p.apurado(j), 100, places=3)
        self.assertEqual(sum(1 for c in p.candidatos(j) if c["eleito"]), 1)           # o TSE só marca o eleito no fim

    def test_no_meio_da_apuracao_ninguem_esta_eleito(self):
        j = self.estado(20, 30)
        self.assertTrue(0 < p.apurado(j) < 100)
        self.assertFalse(any(c["eleito"] for c in p.candidatos(j)))

    def test_o_brasil_e_a_soma_dos_estados(self):
        j = self.brasil(22, 0)
        por_estado = self.votos(self.estado(22, 0))
        for n, v in self.votos(j).items():
            self.assertEqual(v, por_estado[n] * len(p.UFS))
        self.assertEqual(p.apurado(j), 100.0)

    def test_horario_do_arquivo_e_o_relogio_simulado(self):
        self.assertEqual(self.estado(20, 14)["ht"], "20:14:00")

    def test_meta_da_simulacao_tem_relogio_e_contagem(self):
        p.SIM.update(ativo=True, t0=time.time(), duracao=300.0)
        self.addCleanup(lambda: p.SIM.update(ativo=False))
        with unittest.mock.patch.object(p, "t2_disponivel", return_value=False):
            m = p.meta()
        self.assertEqual(m["relogio_sim"], "17:00")
        self.assertTrue(m["simulado"])
        self.assertTrue(m["inicio_2t"].startswith(time.strftime("%Y-%m-%d")))


if __name__ == "__main__":
    unittest.main()
