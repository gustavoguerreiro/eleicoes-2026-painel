"""Avalia a BUSCA nos planos (sem chamar a API, custo zero).

Uso (na pasta backend):
    python -m rag.avaliacao            # imprime hit@1/3/5 e MRR; sai com código 1 se hit@5 < 0,85

Para cada pergunta de data/rag/avaliacao.json, vê em que posição aparece o primeiro trecho do candidato esperado
que contém o fato esperado (regex, sem diferenciar maiúsculas nem acentos).
"""
import json
import os
import re
import sys

from rag.busca import RAIZ, carregar
from rag.texto import sem_acento

ARQUIVO = os.path.join(RAIZ, "data", "rag", "avaliacao.json")
LIMIAR_HIT5 = 0.85


def posicao(resultados, candidato, esperado):
    rx = re.compile(sem_acento(esperado), re.I)
    for pos, r in enumerate(resultados, 1):
        if r["candidato"] == candidato and rx.search(sem_acento(f"{r['secao']} {r['texto']}")):
            return pos
    return None


def avaliar(k=5, verbose=True):
    ix = carregar()
    with open(ARQUIVO, encoding="utf-8") as f:
        casos = json.load(f)["perguntas"]
    pos = []
    for c in casos:
        # sem filtro, pega um pouco mais fundo para saber em que posição o trecho certo aparece
        res = ix.buscar(c["pergunta"], c.get("filtro"), k=10, max_por_pagina=2)
        p = posicao(res, c["candidato"], c["esperado"])
        pos.append(p)
        if verbose:
            print(f"{'OK ' if p and p <= k else 'FALHA'} pos={p!s:>4}  {c['pergunta']}")
    n = len(pos)
    hit = lambda m: sum(1 for p in pos if p and p <= m) / n
    mrr = sum(1 / p for p in pos if p) / n
    return dict(n=n, hit1=hit(1), hit3=hit(3), hit5=hit(5), mrr=mrr)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    m = avaliar()
    print(f"\n{m['n']} perguntas · hit@1 {m['hit1']:.0%} · hit@3 {m['hit3']:.0%} · hit@5 {m['hit5']:.0%} · MRR {m['mrr']:.2f}")
    sys.exit(0 if m["hit5"] >= LIMIAR_HIT5 else 1)
