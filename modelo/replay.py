"""Reproduz a apuração do 2º turno de 2022 minuto a minuto, a partir dos boletins de urna (um por seção, com o horário em que
chegou à totalização). Entrega, para qualquer instante, o que o painel veria: votos e eleitorado já apurados de cada unidade
(estado ou município) e o total de eleitores de cada uma.  Só biblioteca padrão."""
import gzip
import json
import math
import os
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
SECOES = os.path.join(AQUI, "cache", "2022_2t_secoes.jsonl.gz")
MUNIC = os.path.join(AQUI, "cache", "2022_municipios.json")
INICIO = datetime(2022, 10, 30, 0, 0, 0)


def minuto(iso):
    return int((datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S") - INICIO).total_seconds() // 60)


def hhmm(m):
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def carregar_secoes():
    with gzip.open(SECOES, "rt", encoding="utf-8") as f:
        ss = [json.loads(l) for l in f]
    for s in ss:
        s["m"] = minuto(s["t"])
    ss.sort(key=lambda s: s["m"])
    return ss


def carregar_1t():
    """1º turno de 2022 por município: {uf: {mun: {numero: votos}}} (preditor)."""
    with open(MUNIC, encoding="utf-8") as f:
        return json.load(f)["1"]


class Apuracao:
    """Acumula as seções na ordem em que chegaram. unidade = 'uf' (estado) ou 'mun' (município)."""

    def __init__(self, secoes, nivel="uf"):
        self.ss, self.nivel, self.i = secoes, nivel, 0
        self.chave = (lambda s: s["uf"]) if nivel == "uf" else (lambda s: (s["uf"], s["mun"]))
        self.tot = {}                                           # totais finais da unidade (o que o TSE sabe de antemão: eleitorado)
        for s in secoes:
            u = self.tot.setdefault(self.chave(s), dict(apt=0, secoes=0, a=0, b=0))
            u["apt"] += s["aptos"]
            u["secoes"] += 1
            u["a"] += s["a"]
            u["b"] += s["b"]
        self.c = {k: dict(a=0, b=0, apt=0, comp=0, secoes=0, br=0, nu=0) for k in self.tot}
        self.total_secoes = len(secoes)

    def avancar(self, m):
        """Inclui todas as seções recebidas até o minuto m."""
        while self.i < len(self.ss) and self.ss[self.i]["m"] <= m:
            s = self.ss[self.i]
            u = self.c[self.chave(s)]
            u["a"] += s["a"]
            u["b"] += s["b"]
            u["apt"] += s["aptos"]
            u["comp"] += s["comp"]
            u["br"] += s["br"]
            u["nu"] += s["nu"]
            u["secoes"] += 1
            self.i += 1
        return self

    @property
    def pct_secoes(self):
        return self.i / self.total_secoes

    def unidades(self):
        """O que o painel vê agora, uma entrada por unidade."""
        return [dict(id=k, a=v["a"], b=v["b"], apt_c=v["apt"], apt_t=self.tot[k]["apt"], secoes_c=v["secoes"],
                     secoes_t=self.tot[k]["secoes"], comp_c=v["comp"]) for k, v in self.c.items()]

    def verdade(self):
        a = sum(v["a"] for v in self.tot.values())
        b = sum(v["b"] for v in self.tot.values())
        return a / (a + b)


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def invlogit(x):
    return 1 / (1 + math.exp(-x))
