"""Dados do RN para calibrar o modelo do governador:
  (a) 2018: governador 1º e 2º turno por município (Fátima/PT x Carlos Eduardo): um par 1º->2º turno REAL do RN;
  (b) 2026: 1º turno por SEÇÃO com o horário de chegada do boletim (ordem real de apuração no RN em 2026), governador e presidente.
Resultados em modelo/cache/rn_2018_municipios.json e modelo/cache/rn_2026_1t_secoes.jsonl.gz.  Só biblioteca padrão.
Fontes: dadosabertos.tse.jus.br (Votação por seção 2018 RN, 21 MB; Boletim de Urna 2026 RN 1º turno, 54 MB)."""
import csv
import gzip
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
BRUTO = os.path.join(AQUI, "cache", "bruto")
U2018 = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2018_RN.zip"
U2026 = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/buweb/bweb_1t_RN_051020261403.zip"


def baixar(url, nome):
    os.makedirs(BRUTO, exist_ok=True)
    destino = os.path.join(BRUTO, nome)
    if not os.path.exists(destino) or os.path.getsize(destino) < 1000:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 eleicoes-2026-painel"})
        with urllib.request.urlopen(req, timeout=300) as r, open(destino, "wb") as f:
            f.write(r.read())
    return destino


def csv_do_zip(caminho):
    z = zipfile.ZipFile(caminho)
    arq = [i for i in z.infolist() if i.filename.lower().endswith(".csv")][0]
    return csv.DictReader(io.TextIOWrapper(z.open(arq), encoding="latin-1"), delimiter=";")


def rn_2018():
    out = {}
    for r in csv_do_zip(baixar(U2018, "votacao_secao_2018_RN.zip")):
        if r["DS_CARGO"].strip().lower() != "governador":
            continue
        d = out.setdefault(r["NR_TURNO"], {}).setdefault(r["CD_MUNICIPIO"], {})
        d[r["NR_VOTAVEL"]] = d.get(r["NR_VOTAVEL"], 0) + int(r["QT_VOTOS"])
    with open(os.path.join(AQUI, "cache", "rn_2018_municipios.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    for t, ms in out.items():
        a = sum(m.get("13", 0) for m in ms.values())
        b = sum(m.get("12", 0) for m in ms.values())
        print(f"2018 RN governador turno {t}: {len(ms)} municípios | 13: {a:,} | 12: {b:,}")


def rn_2026():
    secs = {}
    nomes = {}
    for r in csv_do_zip(baixar(U2026, "bweb_1t_RN_2026.zip")):
        cargo = r["DS_CARGO_PERGUNTA"]
        if cargo not in ("Governador", "Presidente"):
            continue
        try:
            t = datetime.strptime(r["DT_BU_RECEBIDO"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        k = (r["CD_MUNICIPIO"], r["NR_ZONA"], r["NR_SECAO"])
        s = secs.setdefault(k, dict(mun=r["CD_MUNICIPIO"], t=t.strftime("%Y-%m-%dT%H:%M:%S"), aptos=int(r["QT_APTOS"]),
                                    comp=int(r["QT_COMPARECIMENTO"]), v={}))
        if r["DS_TIPO_VOTAVEL"] == "Nominal":
            d = s["v"].setdefault(cargo[0], {})              # G / P
            d[r["NR_VOTAVEL"]] = d.get(r["NR_VOTAVEL"], 0) + int(r["QT_VOTOS"])
            nomes[(cargo[0], r["NR_VOTAVEL"])] = r["NM_VOTAVEL"]
    with gzip.open(os.path.join(AQUI, "cache", "rn_2026_1t_secoes.jsonl.gz"), "wt", encoding="utf-8") as g:
        for s in secs.values():
            g.write(json.dumps(s, separators=(",", ":")) + "\n")
    print(f"2026 RN 1º turno: {len(secs)} seções;", "candidatos G:", {n: v for (c, n), v in nomes.items() if c == "G"})


if __name__ == "__main__":
    rn_2018()
    rn_2026()
    sys.exit(0)
