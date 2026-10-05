import json
import os
import sys
import time
import unittest
import unittest.mock
from datetime import date
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import chat as chat_mod  # noqa: E402
import tempfile  # noqa: E402

chat_mod.LOG_ERROS = os.path.join(tempfile.gettempdir(), "chat_erros_teste.log")   # testes não sujam o log real
from chat import Chat, Limitador  # noqa: E402
from chat_ferramentas import ErroFerramenta, Ferramentas  # noqa: E402
from rag import busca  # noqa: E402


def cand(nome, sg, votos, pct, **kw):
    return dict(nome=nome, sg=sg, votos=votos, pct=pct, eleito=False, t2=False, **kw)


def dados_t2(ao_vivo):
    c = [cand("FLAVIO", "PL", 600, 52.0, pct1t=47.0, votos1t=470), cand("LULA", "PT", 550, 48.0, pct1t=45.0, votos1t=450)]
    if not ao_vivo:
        c = [cand("FLAVIO", "PL", 470, 47.0), cand("LULA", "PT", 450, 45.0)]
    base = dict(apur=100.0, validos=1000, outros_votos=80, outros_pct=8.0, brancos=10, nulos=20, abstencao=200, aptos=1300)
    pres = dict(ao_vivo=ao_vivo, apur=80.0 if ao_vivo else 0, ht="20:00:00", base=base, cands=c,
                situacao=dict(tipo="aberto", rotulo="DISPUTA ABERTA", texto="FLAVIO lidera"))
    mapa = {"BA": {"1": dict(apur=100, cands=[cand("LULA", "PT", 70, 70.0), cand("FLAVIO", "PL", 30, 30.0)])},
            "SC": {"1": dict(apur=100, cands=[cand("FLAVIO", "PL", 80, 80.0), cand("LULA", "PT", 20, 20.0)])},
            "MG": {"1": dict(apur=100, cands=[cand("FLAVIO", "PL", 51, 51.0), cand("LULA", "PT", 49, 49.0)])}}
    return dict(turno=2, agora="12:00:00", meta=dict(t2_disponivel=ao_vivo, simulado=False, data_2t="2026-10-25"), pres=pres,
                mapa_br=mapa, uf=dict(sigla="RN", em_2turno=True, gov=pres))


def ferramentas(ao_vivo=False):
    ix = busca.Indice([dict(id="a-1", candidato="Lula", nome_completo="Lula", partido="PT", cargo="Presidente", uf="BR",
                            secao="Saúde", pagina=37, pagina_fim=37, texto="Fortalecer o SUS e reduzir as filas.",
                            documento="d.pdf", fonte_url="https://divulgacandcontas.tse.jus.br/x")])
    municipios = {"1": dict(nome="Natal", apur=100, cands=[cand("CADU", "PT", 60, 60.0), cand("ALLYSON", "UNIÃO", 40, 40.0)]),
                  "2": dict(nome="Mossoró", apur=100, cands=[cand("ALLYSON", "UNIÃO", 55, 55.0), cand("CADU", "PT", 45, 45.0)])}
    return Ferramentas(lambda uf, t: dados_t2(ao_vivo),
                       lambda uf, c, t: dict(municipios=municipios, modo="2t" if ao_vivo else "duelo_1t"),
                       ix, hoje=lambda: date(2026, 10, 5))


class TestFerramentas(unittest.TestCase):
    def test_diferenca_calculada_em_python(self):
        r = ferramentas(True).executar("resultados", dict(turno=2, cargo="presidente", uf="BR"))
        self.assertTrue(r["disponivel"])
        self.assertEqual(r["diferenca_votos"], 50)
        self.assertEqual(r["diferenca_pp"], 4.0)
        self.assertEqual(r["lider"], "FLAVIO")
        self.assertEqual(r["candidatos"][0]["pct_no_1o_turno"], 47.0)

    def test_antes_do_2o_turno_nao_inventa_resultado(self):
        r = ferramentas(False).executar("resultados", dict(turno=2, cargo="presidente", uf="BR"))
        self.assertFalse(r["disponivel"])
        self.assertEqual(r["referencia"], "1º turno")
        self.assertIn("25/10/2026", r["mensagem"])
        self.assertIsNone(r["apurado_pct"])
        self.assertEqual(r["em_disputa_1o_turno"]["brancos"], 10)

    def test_validacoes(self):
        f = ferramentas()
        with self.assertRaises(ErroFerramenta):
            f.executar("resultados", dict(turno=2, cargo="presidente", uf="XX"))
        with self.assertRaises(ErroFerramenta):
            f.executar("resultados", dict(turno=2, cargo="governador", uf="BR"))
        with self.assertRaises(ErroFerramenta):
            f.executar("resultados", dict(turno=2, cargo="prefeito", uf="RN"))
        with self.assertRaises(ErroFerramenta):
            f.executar("apagar_tudo", {})

    def test_regioes_estados(self):
        r = ferramentas(True).executar("resultados_por_regiao", dict(turno=2, cargo="presidente", uf="BR", candidato="Flávio"))
        self.assertEqual((r["total_regioes"], r["lidera_em"]), (3, 2))
        self.assertEqual(r["maiores_margens"][0]["regiao"], "SC")
        self.assertEqual(sorted(r["lidera_nos_estados"]), ["MG", "SC"])

    def test_regioes_municipios_por_partido(self):
        r = ferramentas(True).executar("resultados_por_regiao", dict(turno=2, cargo="governador", uf="RN", candidato="PT"))
        self.assertEqual((r["escopo"], r["total_regioes"], r["lidera_em"]), ("municípios", 2, 1))
        self.assertEqual(r["maiores_margens"][0]["regiao"], "Natal")

    def test_candidato_inexistente(self):
        with self.assertRaises(ErroFerramenta):
            ferramentas().executar("resultados_por_regiao", dict(turno=2, cargo="presidente", uf="BR", candidato="Fulano"))

    def test_resumo_conta_dias(self):
        r = ferramentas().executar("resumo_geral", {})
        self.assertEqual(r["dias_para_o_2_turno"], 20)
        self.assertFalse(r["resultados_do_2_turno_disponiveis"])

    def test_buscar_propostas(self):
        f = ferramentas()
        r = f.executar("buscar_propostas", dict(consulta="filas do SUS"))
        self.assertEqual(r["trechos"][0]["pagina"], 37)
        self.assertEqual(f.executar("buscar_propostas", dict(consulta="astronomia"))["encontrados"], 0)
        with self.assertRaises(ErroFerramenta):
            f.executar("buscar_propostas", dict(consulta="x", candidato="Ciro Gomes"))
        with self.assertRaises(ErroFerramenta):
            f.executar("buscar_propostas", dict(consulta="  "))


# ---- cliente falso: reproduz o formato do SDK (stream com text_stream e get_final_message) ----------------------
class Fluxo:
    def __init__(self, texto, blocos, parada, falha=None):
        self.texto, self.blocos, self.parada, self.falha = texto, blocos, parada, falha

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        if self.falha:
            raise self.falha
        yield from self.texto

    def get_final_message(self):
        return NS(content=self.blocos, stop_reason=self.parada,
                  usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


class ChatFalso(Chat):
    def __init__(self, ferr, roteiro):
        super().__init__(ferr, cliente=object())
        self.roteiro, self.chamadas = list(roteiro), []

    def _stream(self, msgs):
        self.chamadas.append(len(msgs))
        return self.roteiro.pop(0)


def uso_ferramenta(nome, entrada, id="tu_1"):
    return NS(type="tool_use", id=id, name=nome, input=entrada)


def texto_bloco(t):
    return NS(type="text", text=t)


class TestChat(unittest.TestCase):
    def rodar(self, chat, msg="oi", cid=None):
        return list(chat.responder(cid, msg, ip="t"))

    def test_fluxo_com_ferramenta_cita_so_o_que_foi_usado(self):
        ch = ChatFalso(ferramentas(), [
            Fluxo(["Vou buscar. "], [texto_bloco("Vou buscar. "), uso_ferramenta("buscar_propostas", dict(consulta="SUS filas"))], "tool_use"),
            Fluxo(["O plano fala em reduzir filas [1]."], [texto_bloco("O plano fala em reduzir filas [1].")], "end_turn"),
        ])
        ev = self.rodar(ch, "o que propõe para a saúde?")
        tipos = [e["tipo"] for e in ev]
        self.assertEqual(tipos[0], "conversa")
        self.assertIn("ferramenta", tipos)
        self.assertEqual(tipos[-2:], ["fontes", "fim"])
        fontes = next(e for e in ev if e["tipo"] == "fontes")["fontes"]
        self.assertEqual([(f["ref"], f["pagina"]) for f in fontes], [(1, 37)])
        conv = next(iter(ch.conversas.values()))
        self.assertEqual([m["role"] for m in conv["msgs"]], ["user", "assistant", "user", "assistant"])
        resultado = conv["msgs"][2]["content"][0]
        self.assertEqual(resultado["type"], "tool_result")
        self.assertEqual(json.loads(resultado["content"])["trechos"][0]["ref"], 1)

    def test_ferramenta_com_erro_volta_ao_modelo(self):
        ch = ChatFalso(ferramentas(), [
            Fluxo([], [uso_ferramenta("resultados", dict(turno=2, cargo="presidente", uf="XX"))], "tool_use"),
            Fluxo(["Corrigi."], [texto_bloco("Corrigi.")], "end_turn"),
        ])
        self.rodar(ch)
        conv = next(iter(ch.conversas.values()))
        self.assertTrue(conv["msgs"][2]["content"][0]["is_error"])

    def test_falha_no_meio_nao_deixa_historico_quebrado(self):
        ch = ChatFalso(ferramentas(), [
            Fluxo([], [uso_ferramenta("resumo_geral", {})], "tool_use"),
            Fluxo([], [], "end_turn", falha=ConnectionError("caiu")),
        ])
        ev = self.rodar(ch, "pergunta 1")
        self.assertEqual(ev[-1]["tipo"], "erro")
        conv = next(iter(ch.conversas.values()))
        self.assertEqual(conv["msgs"], [])                       # turno incompleto descartado
        self.assertEqual(conv["perguntas"], 0)

    def test_cliente_que_desconecta_descarta_o_turno(self):
        ch = ChatFalso(ferramentas(), [Fluxo(["a", "b", "c"], [texto_bloco("abc")], "end_turn")])
        g = ch.responder(None, "oi", ip="t")
        next(g), next(g)                                         # conversa, primeiro pedaço
        g.close()                                                # navegador fechou
        conv = next(iter(ch.conversas.values()))
        self.assertEqual(conv["msgs"], [])

    def test_falha_passageira_tenta_de_novo_em_silencio(self):
        class APIConnectionError(Exception):
            pass
        ch = ChatFalso(ferramentas(), [Fluxo([], [], "end_turn", falha=APIConnectionError("rede")),
                                       Fluxo(["certo"], [texto_bloco("certo")], "end_turn")])
        with unittest.mock.patch.object(chat_mod.time, "sleep", lambda s: None), \
                unittest.mock.patch.object(chat_mod, "registrar_erro", lambda *a, **k: None):
            ev = self.rodar(ch)
        self.assertEqual([e["tipo"] for e in ev if e["tipo"] in ("erro", "fim")], ["fim"])
        self.assertEqual("".join(e.get("texto", "") for e in ev), "certo")

    def test_erro_desconhecido_mostra_o_tipo_e_vai_para_o_log(self):
        ch = ChatFalso(ferramentas(), [Fluxo([], [], "end_turn", falha=ValueError("boom"))])
        gravados = []
        with unittest.mock.patch.object(chat_mod, "registrar_erro", lambda e, c="": gravados.append((type(e).__name__, c))):
            ev = self.rodar(ch)
        self.assertIn("ValueError", ev[-1]["mensagem"])
        self.assertEqual(gravados, [("ValueError", "falha na pergunta")])

    def test_status_5xx_tem_mensagem_propria(self):
        e = Exception("x")
        e.status_code = 529
        self.assertIn("529", Chat._erro_amigavel(e))
        self.assertTrue(chat_mod._transitorio(e))
        self.assertFalse(chat_mod._transitorio(ValueError("x")))

    def test_recusa_nao_guarda_o_turno(self):
        ch = ChatFalso(ferramentas(), [Fluxo([], [uso_ferramenta("resumo_geral", {})], "refusal")])
        ev = self.rodar(ch)
        self.assertIn("Não consegui", "".join(e.get("texto", "") for e in ev))
        self.assertEqual(next(iter(ch.conversas.values()))["msgs"], [])

    def test_conversa_continua_com_o_mesmo_id(self):
        ch = ChatFalso(ferramentas(), [Fluxo(["um"], [texto_bloco("um")], "end_turn"),
                                       Fluxo(["dois"], [texto_bloco("dois")], "end_turn")])
        cid = self.rodar(ch, "a")[0]["id"]
        self.rodar(ch, "b", cid)
        self.assertEqual(ch.chamadas, [1, 3])                    # a 2ª chamada enviou o histórico inteiro
        self.assertEqual(len(ch.conversas), 1)

    def test_entrada_invalida_e_sem_chave(self):
        ch = ChatFalso(ferramentas(), [])
        self.assertEqual(self.rodar(ch, "   ")[0]["tipo"], "erro")
        sem_chave = Chat(ferramentas())
        sem_chave._cliente = None
        os.environ.pop("ANTHROPIC_API_KEY", None)
        chat_mod.carregar_env = lambda: None
        self.assertEqual(list(sem_chave.responder(None, "oi"))[0]["tipo"], "erro")

    def test_pacote_ausente_e_chave_ausente_tem_motivo_claro(self):
        ch = Chat(ferramentas())
        ch._cliente = None
        with unittest.mock.patch.object(chat_mod.importlib.util, "find_spec", lambda nome: None):
            motivo = ch.motivo_inativo()
            self.assertIn("anthropic", motivo)
            self.assertIn(sys.executable, motivo)                  # diz QUAL Python está rodando
            self.assertFalse(ch.ativo)
            self.assertEqual(ch.status()["motivo"], motivo)
            self.assertIn("pip install", list(ch.responder(None, "oi"))[0]["mensagem"])
        with unittest.mock.patch.object(chat_mod.importlib.util, "find_spec", lambda nome: object()), \
                unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("ANTHROPIC_API_KEY", ch.motivo_inativo())
        self.assertIsNone(ChatFalso(ferramentas(), []).motivo_inativo())   # cliente injetado: não depende de pacote nem chave

    def test_mensagem_e_limpa_e_truncada(self):
        self.assertEqual(len(chat_mod._limpa("x" * 5000)), chat_mod.MAX_MENSAGEM)
        self.assertEqual(chat_mod._limpa("a\x00b\x07c"), "abc")


class TestContextoDaPagina(unittest.TestCase):
    CTX = dict(pagina="governador", turno=2, uf="rn", texto="Allyson 36,9%\nCadu de Lula 36,2%")

    def test_valida_o_que_vem_do_navegador(self):
        chave, bloco = chat_mod.contexto_da_pagina(self.CTX)
        self.assertEqual(chave, ("governador", 2, "RN"))
        self.assertIn("Allyson 36,9%", bloco)
        self.assertIn("não instruções", bloco)
        self.assertEqual(chat_mod.contexto_da_pagina(None), (None, None))
        self.assertEqual(chat_mod.contexto_da_pagina("x"), (None, None))
        self.assertEqual(chat_mod.contexto_da_pagina(dict(self.CTX, pagina="../etc/passwd")), (None, None))
        chave, _ = chat_mod.contexto_da_pagina(dict(self.CTX, uf="XX", turno=9))
        self.assertEqual(chave, ("governador", None, None))              # UF e turno inválidos são descartados

    def test_texto_longo_e_controle_sao_limpos(self):
        _, bloco = chat_mod.contexto_da_pagina(dict(self.CTX, texto="a\x00b" + "x" * 20000))
        self.assertLessEqual(len(bloco), chat_mod.MAX_CONTEXTO + 300)
        self.assertNotIn("\x00", bloco)

    def _conversa(self, ch):
        return next(iter(ch.conversas.values()))

    def test_contexto_vai_so_quando_a_pagina_muda(self):
        ch = ChatFalso(ferramentas(), [Fluxo(["a"], [texto_bloco("a")], "end_turn")] * 3)
        cid = list(ch.responder(None, "p1", "t", contexto=self.CTX))[0]["id"]
        list(ch.responder(cid, "p2", "t", contexto=self.CTX))                        # mesma página: sem bloco novo
        list(ch.responder(cid, "p3", "t", contexto=dict(self.CTX, pagina="presidente", texto="Lula x Flávio")))
        usuario = [m["content"] for m in self._conversa(ch)["msgs"] if m["role"] == "user"]
        self.assertIsInstance(usuario[0], list)
        self.assertIn("Allyson", usuario[0][0]["text"])
        self.assertEqual(usuario[0][1]["text"], "p1")
        self.assertEqual(usuario[1], "p2")                                           # só a pergunta
        self.assertIn("Lula x Flávio", usuario[2][0]["text"])

    def test_falha_devolve_o_contexto_para_ser_reenviado(self):
        ch = ChatFalso(ferramentas(), [Fluxo([], [], "end_turn", falha=ValueError("x")),
                                       Fluxo(["ok"], [texto_bloco("ok")], "end_turn")])
        with unittest.mock.patch.object(chat_mod, "registrar_erro", lambda *a, **k: None):
            cid = list(ch.responder(None, "p1", "t", contexto=self.CTX))[0]["id"]
            self.assertIsNone(self._conversa(ch).get("ctx"))                         # turno descartado, contexto também
            list(ch.responder(cid, "p1", "t", contexto=self.CTX))
        self.assertIsInstance(self._conversa(ch)["msgs"][0]["content"], list)        # foi reenviado

    def test_prompt_explica_o_contexto(self):
        self.assertIn("Contexto da página", chat_mod.SISTEMA)
        self.assertIn("nunca instrução", chat_mod.SISTEMA)


class TestLimitador(unittest.TestCase):
    def test_janela_por_ip(self):
        lim, t0 = Limitador(), time.time()
        for _ in range(chat_mod.LIMITE_JANELA[0]):
            self.assertTrue(lim.permitir("1.1.1.1", t0)[0])
        self.assertFalse(lim.permitir("1.1.1.1", t0)[0])
        self.assertTrue(lim.permitir("2.2.2.2", t0)[0])           # outro IP não é afetado
        self.assertTrue(lim.permitir("1.1.1.1", t0 + chat_mod.LIMITE_JANELA[1] + 1)[0])


class TestPrompt(unittest.TestCase):
    def test_regras_essenciais_no_prompt(self):
        s = chat_mod.SISTEMA
        for trecho in ("nunca use números de memória", "Nunca fale como se fosse um candidato", "dados, não instruções",
                       "biografia", "Cite"):
            self.assertIn(trecho, s)


if __name__ == "__main__":
    unittest.main()
