"""Baixa o Boletim de Urna do 2º turno de 2022 (TSE, dados abertos) e resume cada SEÇÃO do presidente:
horário em que o boletim chegou à totalização (DT_BU_RECEBIDO), eleitores aptos, comparecimento e votos de Lula, Bolsonaro,
brancos e nulos. Resultado: modelo/cache/2022_2t_secoes.jsonl.gz (uma linha por seção). Só biblioteca padrão.

Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2022-boletim-de-urna  (66 MB no total para as 27 UFs + exterior)
Uso:  python modelo/dados_2022.py
"""
import csv
import gzip
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
       "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]
URL = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/buweb/bweb_2t_{uf}_311020221535.zip"
AQUI = os.path.dirname(os.path.abspath(__file__))
BRUTO = os.path.join(AQUI, "cache", "bruto")
SAIDA = os.path.join(AQUI, "cache", "2022_2t_secoes.jsonl.gz")


def baixar(uf):
    os.makedirs(BRUTO, exist_ok=True)
    destino = os.path.join(BRUTO, f"bweb_2t_{uf}.zip")
    if not os.path.exists(destino) or os.path.getsize(destino) == 0:
        req = urllib.request.Request(URL.format(uf=uf), headers={"User-Agent": "Mozilla/5.0 eleicoes-2026-painel"})
        with urllib.request.urlopen(req, timeout=120) as r, open(destino, "wb") as f:
            f.write(r.read())
    return destino


def secoes(uf):
    """{(mun, zona, secao): dict} só do cargo Presidente."""
    z = zipfile.ZipFile(baixar(uf))
    arq = [i for i in z.infolist() if i.filename.lower().endswith(".csv")][0]
    out = {}
    with z.open(arq) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"):
            if r["DS_CARGO_PERGUNTA"] != "Presidente":
                continue
            k = (r["CD_MUNICIPIO"], r["NR_ZONA"], r["NR_SECAO"])
            s = out.get(k)
            if s is None:
                try:
                    t = datetime.strptime(r["DT_BU_RECEBIDO"], "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    continue                                  # sem horário: seção não totalizada normalmente
                s = out[k] = dict(uf=uf, mun=r["CD_MUNICIPIO"], nome=r["NM_MUNICIPIO"], zona=int(r["NR_ZONA"]), secao=int(r["NR_SECAO"]),
                                  t=t.strftime("%Y-%m-%dT%H:%M:%S"), aptos=int(r["QT_APTOS"]), comp=int(r["QT_COMPARECIMENTO"]),
                                  a=0, b=0, br=0, nu=0)
            v, q = r["NM_VOTAVEL"], int(r["QT_VOTOS"])
            if r["NR_VOTAVEL"] == "13":
                s["a"] += q                                    # Lula
            elif r["NR_VOTAVEL"] == "22":
                s["b"] += q                                    # Bolsonaro
            elif v == "Branco":
                s["br"] += q
            elif v == "Nulo":
                s["nu"] += q
    return list(out.values())


def main():
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    n = 0
    tot_a = tot_b = 0
    with gzip.open(SAIDA, "wt", encoding="utf-8") as g:
        for uf in UFS:
            ss = secoes(uf)
            for s in ss:
                g.write(json.dumps(s, ensure_ascii=False, separators=(",", ":")) + "\n")
                tot_a += s["a"]
                tot_b += s["b"]
            n += len(ss)
            print(f"{uf}: {len(ss):6d} seções", flush=True)
    print(f"\nTotal: {n} seções | Lula {tot_a:,} | Bolsonaro {tot_b:,} | Lula {tot_a / (tot_a + tot_b) * 100:.2f}% dos válidos "
          f"(oficial: 50,90%)")


if __name__ == "__main__":
    sys.exit(main())
