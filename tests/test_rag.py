import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from rag import avaliacao, busca, texto  # noqa: E402


class TestLimpeza(unittest.TestCase):
    def test_letras_espacadas(self):
        self.assertEqual(texto.juntar_letras_espacadas("P R O G R A M A"), "PROGRAMA")
        self.assertEqual(texto.juntar_letras_espacadas("Vamos fortalecer o SUS"), "Vamos fortalecer o SUS")

    def test_caractere_combinante_do_pdf_vira_r(self):
        self.assertEqual(texto.limpar_texto("const̵uindo"), "construindo")

    def test_hifen_opcional_e_quebra_de_linha(self):
        self.assertEqual(texto.limpar_texto("solu­ção\nde teste"), "solução de teste")
        self.assertEqual(texto.limpar_texto("educa-\nção"), "educação")

    def test_sumario_e_descartado(self):
        self.assertTrue(texto.e_indice("Saúde ......................... 12"))
        self.assertFalse(texto.e_indice("Vamos ampliar o acesso à saúde."))

    def test_numero_de_pagina(self):
        self.assertTrue(texto.e_numero_de_pagina("12"))
        self.assertTrue(texto.e_numero_de_pagina("Página 3"))
        self.assertFalse(texto.e_numero_de_pagina("12 hospitais"))

    def test_tokens_sem_acento_stopwords_e_plural(self):
        self.assertEqual(texto.tokens("As escolas públicas e as Universidades"), ["escola", "publica", "universidade"])
        self.assertEqual(texto.tokens("educações"), texto.tokens("EDUCAÇÃO"))
        self.assertEqual(texto.tokens("ações"), texto.tokens("ação"))


def _t(i, cand, pag, secao, txt):
    return dict(id=i, candidato=cand, nome_completo=cand, partido="X", cargo="Presidente", uf="BR", secao=secao,
                pagina=pag, pagina_fim=pag, texto=txt, documento="d.pdf", fonte_url="https://x")


class TestBusca(unittest.TestCase):
    def setUp(self):
        self.ix = busca.Indice([
            _t("1", "Ana", 1, "Saúde", "Vamos ampliar o SUS e reduzir as filas de espera nos hospitais."),
            _t("2", "Ana", 2, "Educação", "Escolas em tempo integral e valorização dos professores."),
            _t("3", "Beto", 1, "Segurança", "Mais presídios e policiamento nas ruas, combate às facções."),
            _t("4", "Beto", 2, "Saúde", "Atendimento nos postos de saúde e vacinação para todos."),
            _t("5", "Beto", 2, "Economia", "Reforma tributária e redução de impostos para empresas."),
        ])

    def test_acha_o_trecho_certo(self):
        r = self.ix.buscar("filas no SUS")
        self.assertEqual(r[0]["id"], "1")

    def test_filtro_por_candidato(self):
        r = self.ix.buscar("saúde", "Beto")
        self.assertTrue(r and all(x["candidato"] == "Beto" for x in r))
        self.assertEqual(r[0]["id"], "4")

    def test_acento_nao_importa(self):
        self.assertEqual(self.ix.buscar("seguranca presidios")[0]["id"], "3")

    def test_sem_resultado(self):
        self.assertEqual(self.ix.buscar("astronomia"), [])

    def test_limite_por_pagina(self):
        ix = busca.Indice([_t(str(i), "Ana", 1, "Saúde", "saúde hospital SUS") for i in range(5)])
        self.assertEqual(len(ix.buscar("saúde", max_por_pagina=2)), 2)

    def test_documentos(self):
        d = {x["candidato"]: x for x in self.ix.documentos()}
        self.assertEqual(d["Ana"]["trechos"], 2)
        self.assertEqual(d["Beto"]["paginas"], 2)


@unittest.skipUnless(os.path.exists(busca.ARQUIVO), "rode `python -m rag.ingestao` antes")
class TestQualidadeDaBusca(unittest.TestCase):
    def test_hit_at_5_acima_do_limiar(self):
        m = avaliacao.avaliar(verbose=False)
        self.assertGreaterEqual(m["hit5"], avaliacao.LIMIAR_HIT5, m)

    def test_corpus_sem_lixo_de_extracao(self):
        ix = busca.carregar()
        for t in ix.trechos:
            self.assertNotIn("̵", t["texto"])
            self.assertNotRegex(t["texto"], r"\.{5,}")
            self.assertLessEqual(len(t["texto"]), 1600)
            self.assertTrue(t["pagina"] and t["fonte_url"].startswith("https://divulgacandcontas.tse.jus.br/"))


if __name__ == "__main__":
    unittest.main()
