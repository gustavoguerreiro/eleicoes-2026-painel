"""Ingestão dos planos de governo: PDF -> trechos com metadados (candidato, página, seção, fonte).

Uso (na pasta backend):
    python -m rag.ingestao            # lê data/planos/manifesto.json e grava data/rag/trechos.jsonl

Cada trecho guarda a página de origem e a seção (título mais próximo, detectado pelo tamanho da fonte), para que o
chat consiga citar "Plano de governo de X, p. N — Saúde".
"""
import json
import os
import re
import statistics
import sys
from collections import Counter

import fitz  # PyMuPDF

from rag.texto import e_indice, e_numero_de_pagina, juntar_letras_espacadas, limpar_texto, sem_acento

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
PLANOS = os.path.join(RAIZ, "data", "planos")
SAIDA = os.path.join(RAIZ, "data", "rag", "trechos.jsonl")

ALVO, MAXIMO, MINIMO = 900, 1300, 250        # tamanho dos trechos, em caracteres


def blocos_do_pdf(caminho):
    """[(pagina, texto, é_título)] já na ordem de leitura. Título = fonte bem maior que o corpo (ou negrito curto em caixa alta)."""
    doc = fitz.open(caminho)
    brutos, tamanhos = [], []
    for n, pag in enumerate(doc, 1):
        for b in pag.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            linhas = []
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                linhas.append(("".join(s["text"] for s in spans), max(s["size"] for s in spans),
                               all(s["flags"] & 16 for s in spans)))
            if not linhas:
                continue
            texto = "\n".join(t for t, _, _ in linhas)
            tam = statistics.mean(s for _, s, _ in linhas)
            negrito = all(nb for _, _, nb in linhas)
            brutos.append((n, texto, tam, negrito))
            tamanhos += [tam] * max(1, len(texto) // 20)
    corpo = statistics.median(tamanhos) if tamanhos else 10
    blocos = []
    for n, texto, tam, negrito in brutos:
        plano = " ".join(texto.split())
        # título: fonte bem maior que o corpo, ou negrito curto (não menor que o corpo) que não termina em ponto
        titulo = (len(plano) < 150 and tam >= corpo * 1.18) or (
            negrito and 3 < len(plano) < 130 and tam >= corpo * 0.98 and not plano.endswith((".", ";", ",")))
        blocos.append((n, texto, titulo))
    return blocos


def filtrar(blocos, total_paginas):
    """Tira número de página, sumário e cabeçalho/rodapé que se repete em muitas páginas."""
    cont = Counter(re.sub(r"\d+", "#", sem_acento(limpar_texto(t)).lower())
                   for _, t, _ in blocos if len(t) < 90)
    repetido = {k for k, v in cont.items() if v >= max(4, 0.25 * total_paginas)}
    out = []
    for n, t, tit in blocos:
        limpo = limpar_texto(t)
        if not limpo or e_numero_de_pagina(limpo) or e_indice(limpo):
            continue
        if len(limpo) < 90 and re.sub(r"\d+", "#", sem_acento(limpo).lower()) in repetido:
            continue
        out.append((n, limpo, tit))
    return out


def frases(texto):
    return [f.strip() for f in re.split(r"(?<=[.!?;:])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ•\-0-9])", texto) if f.strip()]


def quebrar(texto):
    """Divide um bloco muito grande em pedaços de até MAXIMO caracteres, em fronteira de frase."""
    if len(texto) <= MAXIMO:
        return [texto]
    partes, atual = [], ""
    for f in frases(texto):
        while len(f) > MAXIMO:                                    # sequência sem pontuação: corta no último espaço
            corte = f.rfind(" ", 0, ALVO) or ALVO
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(f[:corte])
            f = f[corte:].strip()
        if atual and len(atual) + len(f) + 1 > ALVO:
            partes.append(atual)
            atual = ""
        atual = (atual + " " + f).strip()
    if atual:
        partes.append(atual)
    return partes


def trechos_do_documento(plano):
    caminho = os.path.join(PLANOS, plano["arquivo_local"])
    total = len(fitz.open(caminho))
    blocos = filtrar(blocos_do_pdf(caminho), total)
    base = re.sub(r"[^a-z0-9]+", "-", sem_acento(plano["nome_urna"]).lower()).strip("-") + "-" + plano["cargo"].lower()[:4]
    out, secao, buf, pag0, pag1 = [], "", [], None, None

    def fechar():
        nonlocal buf, pag0, pag1
        texto = " ".join(buf).strip()
        cola = (out and out[-1]["secao"] == secao and len(texto) < MINIMO
                and len(out[-1]["texto"]) + len(texto) < MAXIMO)      # só cola resto curto da MESMA seção
        if len(texto) >= 40 and not cola:
            out.append(dict(id=f"{base}-{len(out) + 1:04d}", candidato=plano["nome_urna"], nome_completo=plano["candidato"],
                            partido=plano["partido"], cargo=plano["cargo"], uf=plano["uf"], secao=secao, pagina=pag0,
                            pagina_fim=pag1, texto=texto, documento=plano["nome_arquivo_original"], fonte_url=plano["url"]))
        elif texto and cola:
            out[-1]["texto"] += " " + texto
            out[-1]["pagina_fim"] = pag1
        buf, pag0, pag1 = [], None, None

    for n, texto, titulo in blocos:
        if titulo:
            fechar()
            secao = juntar_letras_espacadas(texto).strip()[:90]
            continue
        for parte in quebrar(texto):
            if buf and sum(len(x) for x in buf) + len(parte) > MAXIMO:
                fechar()
            if not buf:
                pag0 = n
            buf.append(parte)
            pag1 = n
            if sum(len(x) for x in buf) >= ALVO:
                fechar()
    fechar()
    return out


def main():
    manifesto = json.load(open(os.path.join(PLANOS, "manifesto.json"), encoding="utf-8"))
    todos = []
    for plano in manifesto["planos"]:
        ts = trechos_do_documento(plano)
        print(f"{plano['nome_urna']:18s} {plano['cargo']:10s} {len(ts):4d} trechos, "
              f"{sum(len(t['texto']) for t in ts):7d} caracteres, páginas {min(t['pagina'] for t in ts)}-{max(t['pagina_fim'] for t in ts)}")
        todos += ts
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        for t in todos:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\n{len(todos)} trechos gravados em {os.path.relpath(SAIDA, RAIZ)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
