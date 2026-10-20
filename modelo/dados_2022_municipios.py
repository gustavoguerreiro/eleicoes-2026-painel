"""Baixa o Presidente "votação por seção" de 2022 (TSE, dados abertos; 271 MB) e resume por município:
votos de cada candidato nos dois turnos. Serve de PREDITOR do modelo (1º turno de 2022 -> 2º turno de 2022).
Resultado: modelo/cache/2022_municipios.json   {turno: {uf: {municipio: {numero_do_votavel: votos}}}}
Fonte: https://dadosabertos.tse.jus.br/dataset/resultados-2022  ("Presidente - Votação por seção eleitoral - 2022")
Uso:  python modelo/dados_2022_municipios.py
"""
import csv
import io
import json
import os
import sys
import urllib.request
import zipfile

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/votacao_secao_2022_BR.zip"
AQUI = os.path.dirname(os.path.abspath(__file__))
ZIP = os.path.join(AQUI, "cache", "bruto", "votacao_secao_2022_BR.zip")
SAIDA = os.path.join(AQUI, "cache", "2022_municipios.json")


def baixar():
    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    if os.path.exists(ZIP) and os.path.getsize(ZIP) > 200_000_000:
        return
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 eleicoes-2026-painel"})
    with urllib.request.urlopen(req, timeout=300) as r, open(ZIP + ".parte", "wb") as f:
        while True:
            bloco = r.read(1 << 20)
            if not bloco:
                break
            f.write(bloco)
    os.replace(ZIP + ".parte", ZIP)


def main():
    baixar()
    z = zipfile.ZipFile(ZIP)
    print([(i.filename, i.file_size // 1048576) for i in z.infolist()])
    arq = [i for i in z.infolist() if i.filename.lower().endswith(".csv")][0]
    agg, n = {}, 0
    with z.open(arq) as f:
        rd = csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")
        for r in rd:
            if r["DS_CARGO"].strip().lower() != "presidente":
                continue
            d = agg.setdefault(r["NR_TURNO"], {}).setdefault(r["SG_UF"], {}).setdefault(r["CD_MUNICIPIO"], {})
            nr = r["NR_VOTAVEL"]
            d[nr] = d.get(nr, 0) + int(r["QT_VOTOS"])
            n += 1
            if n % 2_000_000 == 0:
                print(f"{n:,} linhas...", flush=True)
    with open(SAIDA, "w", encoding="utf-8") as g:
        json.dump(agg, g, separators=(",", ":"))
    for t, ufs in agg.items():
        a = sum(m.get("13", 0) for u in ufs.values() for m in u.values())
        b = sum(m.get("22", 0) for u in ufs.values() for m in u.values())
        nm = sum(len(u) for u in ufs.values())
        print(f"turno {t}: {nm} municípios | Lula {a:,} | Bolsonaro {b:,} | Lula {a / (a + b) * 100:.2f}% entre os dois")
    return 0


if __name__ == "__main__":
    sys.exit(main())
