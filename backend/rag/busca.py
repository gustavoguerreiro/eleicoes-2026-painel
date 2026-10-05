"""Busca nos planos de governo: BM25 sobre os trechos, com normalização para o português.

Por que BM25 e não embeddings: o corpus é pequeno (centenas de trechos), o vocabulário é técnico e repetido, e quem
reformula a pergunta em termos do plano é o próprio modelo (a ferramenta recebe a consulta que ele escreveu, com
sinônimos). Isso dá boa revocação sem dependência pesada. O ponto de troca para busca densa está em `Indice.pontuar`.
"""
import json
import math
import os
from collections import Counter, defaultdict

from rag.texto import sem_acento, tokens

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
ARQUIVO = os.path.join(RAIZ, "data", "rag", "trechos.jsonl")

CAMPOS_PUBLICOS = ("id", "candidato", "cargo", "uf", "partido", "secao", "pagina", "pagina_fim", "texto", "fonte_url", "documento")


def _chave(nome):
    return sem_acento(str(nome)).lower().strip()


class Indice:
    K1, B = 1.5, 0.75

    def __init__(self, trechos):
        self.trechos = trechos
        self.tf = []                                   # um Counter por trecho
        self.comp = []
        self.df = Counter()
        self.invertido = defaultdict(list)
        for i, t in enumerate(trechos):
            # o título da seção pesa o dobro: "Saúde" no título diz mais do que uma menção solta no texto
            toks = tokens(t["texto"]) + tokens(t.get("secao", "")) * 2
            c = Counter(toks)
            self.tf.append(c)
            self.comp.append(len(toks))
            for w in c:
                self.df[w] += 1
                self.invertido[w].append(i)
        self.n = len(trechos)
        self.media = sum(self.comp) / max(self.n, 1)

    def idf(self, w):
        return math.log(1 + (self.n - self.df[w] + 0.5) / (self.df[w] + 0.5))

    def pontuar(self, consulta, permitidos=None):
        """{índice do trecho: pontuação BM25}. É aqui que entraria uma busca densa/híbrida."""
        pontos = defaultdict(float)
        for w in set(tokens(consulta)):
            if w not in self.invertido:
                continue
            idf = self.idf(w)
            for i in self.invertido[w]:
                if permitidos is not None and i not in permitidos:
                    continue
                f = self.tf[i][w]
                pontos[i] += idf * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * self.comp[i] / self.media))
        return pontos

    def buscar(self, consulta, candidato=None, k=6, max_por_pagina=2):
        permitidos = None
        if candidato:
            alvo = _chave(candidato)
            permitidos = {i for i, t in enumerate(self.trechos)
                          if alvo in _chave(t["candidato"]) or alvo in _chave(t.get("nome_completo", ""))}
        pontos = self.pontuar(consulta, permitidos)
        saida, por_pagina = [], Counter()
        for i, p in sorted(pontos.items(), key=lambda x: -x[1]):
            t = self.trechos[i]
            chave = (t["candidato"], t["pagina"])
            if por_pagina[chave] >= max_por_pagina:        # evita 5 resultados da mesma página
                continue
            por_pagina[chave] += 1
            saida.append(dict({c: t.get(c) for c in CAMPOS_PUBLICOS}, pontuacao=round(p, 2)))
            if len(saida) >= k:
                break
        return saida

    def documentos(self):
        docs = {}
        for t in self.trechos:
            d = docs.setdefault(t["candidato"], dict(candidato=t["candidato"], nome_completo=t.get("nome_completo"),
                                                     partido=t["partido"], cargo=t["cargo"], uf=t["uf"],
                                                     documento=t["documento"], trechos=0, paginas=0))
            d["trechos"] += 1
            d["paginas"] = max(d["paginas"], t["pagina_fim"] or t["pagina"])
        return list(docs.values())


_cache = {}


def carregar(arquivo=ARQUIVO):
    if arquivo not in _cache:
        with open(arquivo, encoding="utf-8") as f:
            _cache[arquivo] = Indice([json.loads(l) for l in f if l.strip()])
    return _cache[arquivo]
