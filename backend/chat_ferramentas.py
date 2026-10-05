"""Ferramentas do chat: planos de governo (RAG) e números da apuração (os mesmos do painel).

O modelo nunca faz conta nem lembra número: tudo vem daqui, calculado em Python a partir dos dados do TSE que o painel
já mantém em cache. Cada ferramenta devolve um dicionário simples (vira JSON para o modelo) e, quando for o caso, uma
lista de trechos para o chat poder citar a página de origem.
"""
from datetime import date, datetime

from rag.texto import sem_acento

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
       "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
CARGOS = {"presidente": "1", "governador": "3", "senador": "5"}
CANDIDATOS = ["Lula", "Flávio Bolsonaro", "Cadu de Lula", "Allyson"]

DEFINICOES = [
    {
        "name": "buscar_propostas",
        "description": (
            "Busca trechos dos planos de governo registrados no TSE (Lula e Flávio Bolsonaro para presidente; Cadu de "
            "Lula e Allyson para governador do RN). Escreva a consulta com os termos que o plano provavelmente usa, "
            "incluindo sinônimos (ex.: 'SUS atenção primária hospitais filas'). Sem `candidato`, devolve os melhores "
            "trechos DE CADA candidato, o que serve para comparar. Cada trecho vem com um número `ref` para citar."),
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {"type": "string", "description": "Termos de busca do tema."},
                "candidato": {"type": "string", "enum": CANDIDATOS,
                              "description": "Restringe a um candidato. Omita para comparar todos."},
                "cargo": {"type": "string", "enum": ["Presidente", "Governador"],
                          "description": "Restringe ao plano de presidente ou de governador do RN."},
                "quantidade": {"type": "integer", "minimum": 1, "maximum": 6,
                               "description": "Trechos por candidato (padrão 3 sem candidato, 5 com candidato)."},
            },
            "required": ["consulta"],
        },
    },
    {
        "name": "resultados",
        "description": (
            "Resultado da apuração do TSE para presidente ou governador, no 1º ou no 2º turno. Devolve candidatos, "
            "votos, percentuais sobre votos válidos, percentual apurado, situação e a vantagem do 1º sobre o 2º já "
            "calculada em votos e em pontos percentuais. Use `uf='BR'` para o total nacional do presidente; para uma "
            "UF, o resultado do presidente naquele estado ou do governador. No 2º turno antes de 25/10 ainda não há "
            "resultados: a ferramenta devolve `disponivel: false` e o desempenho dos finalistas no 1º turno."),
        "input_schema": {
            "type": "object",
            "properties": {
                "turno": {"type": "integer", "enum": [1, 2]},
                "cargo": {"type": "string", "enum": ["presidente", "governador"]},
                "uf": {"type": "string", "description": "'BR' (só presidente) ou a sigla da UF, ex.: 'RN'."},
            },
            "required": ["turno", "cargo", "uf"],
        },
    },
    {
        "name": "resultados_por_regiao",
        "description": (
            "Onde um candidato vai bem ou mal: em quantos estados (uf='BR') ou municípios (uf = sigla) ele lidera, "
            "com as maiores e menores margens. Antes do 2º turno, usa o desempenho dos dois finalistas no 1º turno."),
        "input_schema": {
            "type": "object",
            "properties": {
                "turno": {"type": "integer", "enum": [1, 2]},
                "cargo": {"type": "string", "enum": ["presidente", "governador"]},
                "uf": {"type": "string", "description": "'BR' para estados (só presidente) ou a sigla da UF para municípios."},
                "candidato": {"type": "string", "description": "Nome ou partido, ex.: 'Lula', 'Flávio', 'PT'."},
            },
            "required": ["turno", "cargo", "uf", "candidato"],
        },
    },
    {
        "name": "resumo_geral",
        "description": "Visão geral do momento: turno em curso, dias para o 2º turno, duelo presidencial e duelo do RN.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "listar_documentos",
        "description": "Lista os planos de governo carregados (candidato, cargo, partido, páginas) e a fonte de cada um.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

ROTULOS = {
    "buscar_propostas": "Buscando nos planos de governo",
    "resultados": "Consultando os resultados do TSE",
    "resultados_por_regiao": "Comparando regiões nos resultados",
    "resumo_geral": "Consultando o resumo da eleição",
    "listar_documentos": "Conferindo os documentos disponíveis",
}


def _n(s):
    return sem_acento(str(s)).lower().strip()


class ErroFerramenta(Exception):
    """Entrada inválida: o texto é devolvido ao modelo como resultado de erro, para ele se corrigir."""


class Ferramentas:
    """`obter(uf, turno)` -> dados do /api; `mapa(uf, cargo, turno)` -> dados do /api/mapa; `indice` -> rag.busca.Indice."""

    def __init__(self, obter, mapa, indice, hoje=None):
        self.obter, self.mapa, self.indice = obter, mapa, indice
        self.hoje = hoje or date.today

    # ---- despacho --------------------------------------------------------------------------------------------------
    def executar(self, nome, entrada):
        if not isinstance(entrada, dict):
            raise ErroFerramenta("entrada inválida")
        fn = getattr(self, "_" + nome, None)
        if nome not in ROTULOS or fn is None:
            raise ErroFerramenta(f"ferramenta desconhecida: {nome}")
        return fn(**entrada)

    # ---- planos ----------------------------------------------------------------------------------------------------
    def _buscar_propostas(self, consulta, candidato=None, cargo=None, quantidade=None):
        if not isinstance(consulta, str) or not consulta.strip():
            raise ErroFerramenta("consulta vazia")
        consulta = consulta.strip()[:300]
        if candidato and candidato not in CANDIDATOS:
            raise ErroFerramenta(f"candidato sem plano carregado: {candidato}. Disponíveis: {', '.join(CANDIDATOS)}")
        k = int(quantidade) if quantidade else (5 if candidato else 3)
        k = max(1, min(k, 6))
        if candidato:
            trechos = self.indice.buscar(consulta, candidato, k=k)
        else:
            alvos = [d["candidato"] for d in self.indice.documentos() if not cargo or d["cargo"] == cargo]
            trechos = []
            for c in alvos:
                trechos += self.indice.buscar(consulta, c, k=k)
        trechos = [t for t in trechos if t["pontuacao"] > 0]
        if not trechos:
            return {"encontrados": 0, "trechos": [],
                    "aviso": "Nenhum trecho dos planos trata disso. Diga ao usuário que não encontrou nos planos."}
        return {"encontrados": len(trechos), "trechos": trechos}

    def _listar_documentos(self):
        return {"documentos": self.indice.documentos(),
                "observacao": "Planos registrados no TSE (DivulgaCandContas). Não há outros candidatos carregados."}

    # ---- resultados ------------------------------------------------------------------------------------------------
    @staticmethod
    def _uf(uf):
        uf = str(uf).upper().strip()
        if uf != "BR" and uf not in UFS:
            raise ErroFerramenta(f"UF inválida: {uf}")
        return uf

    @staticmethod
    def _cargo(cargo):
        if cargo not in ("presidente", "governador"):
            raise ErroFerramenta("cargo deve ser 'presidente' ou 'governador'")
        return cargo

    @staticmethod
    def _cand(c, turno, ao_vivo):
        d = dict(nome=c["nome"], partido=c["sg"], votos=int(c["votos"]), pct_validos=round(c["pct"], 2))
        if turno == 2:
            d["pct_no_1o_turno"] = round(c.get("pct1t", c["pct"]), 2)
            d["votos_no_1o_turno"] = int(c.get("votos1t", c["votos"]))
        return d

    @staticmethod
    def _vantagem(cands):
        if len(cands) < 2:
            return {}
        a, b = cands[0], cands[1]
        return dict(lider=a["nome"], segundo=b["nome"], diferenca_votos=int(a["votos"] - b["votos"]),
                    diferenca_pp=round(a["pct"] - b["pct"], 2))

    def _resultados(self, turno, cargo, uf):
        turno, cargo, uf = int(turno), self._cargo(cargo), self._uf(uf)
        if turno not in (1, 2):
            raise ErroFerramenta("turno deve ser 1 ou 2")
        if cargo == "governador" and uf == "BR":
            raise ErroFerramenta("governador exige uma UF (ex.: 'RN')")
        base_uf = "RN" if uf == "BR" else uf
        d = self.obter(base_uf, turno)
        fonte = f"TSE, divulgação de resultados (consulta às {d.get('agora', '?')})"

        if cargo == "presidente" and uf == "BR":
            bloco = d.get("pres")
        elif cargo == "presidente":
            r = (d.get("mapa_br") or {}).get(uf, {}).get("1")
            bloco = None if not r else dict(apur=r["apur"], ht="", situacao=None, cands=r["cands"],
                                            ao_vivo=turno == 2 and d["meta"]["t2_disponivel"])
        else:
            u = d.get("uf") or {}
            if turno == 2 and not u.get("em_2turno"):
                return dict(turno=2, cargo=cargo, uf=uf, disponivel=False, fonte=fonte,
                            mensagem=f"O governo de {uf} foi decidido no 1º turno; não há 2º turno para governador.")
            bloco = u.get("gov")
        if not bloco or not bloco.get("cands"):
            return dict(turno=turno, cargo=cargo, uf=uf, disponivel=False, fonte=fonte, mensagem="Sem dados ainda.")

        ao_vivo = bool(bloco.get("ao_vivo", turno == 1))
        meta = d.get("meta", {})
        out = dict(turno=turno, cargo=cargo, uf=uf, fonte=fonte, simulado=bool(meta.get("simulado")))
        if turno == 2 and not ao_vivo:
            iso = meta.get("data_2t", "2026-10-25")
            out.update(disponivel=False, referencia="1º turno",
                       mensagem=f"O 2º turno é em {iso[8:]}/{iso[5:7]}/{iso[:4]}; ainda não há resultados. "
                                "Abaixo, o desempenho dos finalistas no 1º turno.")
        else:
            out["disponivel"] = True
        sit = bloco.get("situacao") or {}
        out.update(apurado_pct=round(bloco["apur"], 2) if out["disponivel"] else None,
                   atualizado_tse=bloco.get("ht") or None,
                   situacao=f"{sit.get('rotulo', '')}: {sit.get('texto', '')}".strip(": ") or None,
                   candidatos=[self._cand(c, turno, ao_vivo) for c in bloco["cands"]])
        out.update(self._vantagem(bloco["cands"]))
        if turno == 2 and ao_vivo and bloco.get("base"):
            out["votos_validos_1o_turno"] = int(bloco["base"]["validos"])
        if not out["disponivel"] and bloco.get("base"):
            out["apurado_1o_turno_pct"] = round(bloco["base"]["apur"], 2)
        if turno == 2 and bloco.get("base"):
            b = bloco["base"]
            out["em_disputa_1o_turno"] = dict(
                votos_de_candidatos_eliminados=int(b["outros_votos"]), pct_dos_validos=round(b["outros_pct"], 2),
                brancos=int(b["brancos"]), nulos=int(b["nulos"]), abstencao=int(b["abstencao"]))
        return out

    # ---- por região ------------------------------------------------------------------------------------------------
    @staticmethod
    def _acha(cands, quem):
        q = _n(quem)
        for c in cands:
            if q and (q in _n(c["nome"]) or _n(c["nome"]) in q or q == _n(c["sg"])):
                return c
        return None

    def _resultados_por_regiao(self, turno, cargo, uf, candidato):
        turno, cargo, uf = int(turno), self._cargo(cargo), self._uf(uf)
        cod = CARGOS[cargo]
        if uf == "BR":
            if cargo != "presidente":
                raise ErroFerramenta("para governador informe uma UF; 'BR' só vale para presidente")
            d = self.obter("RN", turno)
            regioes = {u: v[cod] for u, v in (d.get("mapa_br") or {}).items() if v.get(cod)}
            escopo, nomes = "estados", {u: u for u in regioes}
            ao_vivo = turno == 2 and d["meta"]["t2_disponivel"]
        else:
            m = self.mapa(uf, int(cod), turno)
            regioes = m.get("municipios", {})
            escopo, nomes = "municípios", {k: v["nome"] for k, v in regioes.items()}
            ao_vivo = turno == 2 and m.get("modo") == "2t"
        if not regioes:
            return dict(disponivel=False, mensagem="Sem dados por região ainda.")
        linhas, lidera, sem = [], 0, 0
        alvo_nome = None
        for k, r in regioes.items():
            c = self._acha(r["cands"], candidato)
            if not c:
                sem += 1
                continue
            alvo_nome = c["nome"]
            outros = [x["pct"] for x in r["cands"] if x is not c]
            margem = c["pct"] - max(outros) if outros else None
            if r["cands"][0] is c:
                lidera += 1
            linhas.append((nomes[k], round(c["pct"], 2), None if margem is None else round(margem, 2)))
        if not linhas:
            raise ErroFerramenta(f"não achei '{candidato}' entre os candidatos desta eleição")
        ordem = sorted((l for l in linhas if l[2] is not None), key=lambda l: -l[2])
        fmt = lambda l: dict(regiao=l[0], pct_validos=l[1], margem_pp=l[2])
        apur = [r["apur"] for r in regioes.values() if r.get("apur") is not None]
        out = dict(disponivel=True, turno=turno, cargo=cargo, uf=uf, candidato=alvo_nome, escopo=escopo,
                   fonte="TSE, divulgação de resultados",
                   apuracao_media_das_regioes_pct=round(sum(apur) / len(apur), 1) if apur else None,
                   base="resultado do 2º turno" if ao_vivo else ("1º turno" if turno == 1 else "1º turno (os dois finalistas)"),
                   total_regioes=len(regioes), lidera_em=lidera, nao_lidera_em=len(linhas) - lidera,
                   maiores_margens=[fmt(l) for l in ordem[:6]], menores_margens=[fmt(l) for l in ordem[-4:]],
                   observacao="margem_pp = pontos percentuais do candidato menos o melhor adversário na região (negativo = atrás).")
        if lidera <= 30 and escopo == "estados":
            out["lidera_nos_estados"] = sorted(l[0] for l in ordem if l[2] > 0)
        if sem:
            out["regioes_sem_o_candidato_entre_os_mais_votados"] = sem
        return out

    # ---- resumo ----------------------------------------------------------------------------------------------------
    def _resumo_geral(self):
        d = self.obter("RN", 2)
        meta = d.get("meta", {})
        iso = meta.get("data_2t", "2026-10-25")
        dias = (date.fromisoformat(iso) - self.hoje()).days
        out = dict(data_2t=iso, dias_para_o_2_turno=dias, resultados_do_2_turno_disponiveis=bool(meta.get("t2_disponivel")),
                   simulado=bool(meta.get("simulado")), agora=datetime.now().strftime("%d/%m/%Y %H:%M"))
        for rotulo, args in (("presidente", (2, "presidente", "BR")), ("governador_rn", (2, "governador", "RN"))):
            try:
                out[rotulo] = self._resultados(*args)
            except ErroFerramenta as e:
                out[rotulo] = {"erro": str(e)}
        return out
