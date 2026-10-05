"""Malhas e nomes do IBGE (API de malhas v3 e localidades v1), com cache em disco em data/geo/."""
import json
import os
import urllib.request

IBGE = "https://servicodados.ibge.gov.br/api"
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "geo")


def _cache(nome, url, binario=False):
    os.makedirs(DIR, exist_ok=True)
    caminho = os.path.join(DIR, nome)
    if not os.path.exists(caminho) or os.path.getsize(caminho) == 0:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 eleicoes-2026-painel"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dados = r.read()
        with open(caminho, "wb") as f:
            f.write(dados)
    with open(caminho, "rb") as f:
        return f.read()


def geojson_br():
    """Estados do Brasil (properties.codarea = código IBGE da UF)."""
    return _cache("br_uf.geojson", f"{IBGE}/v3/malhas/paises/BR?formato=application/vnd.geo+json&intrarregiao=UF&qualidade=minima")


def geojson_uf(uf):
    """Municípios da UF (properties.codarea = código IBGE de 7 dígitos)."""
    uf = uf.upper()
    q = "intermediaria" if uf not in ("MG", "BA", "GO", "PA", "MT", "RS", "SP", "TO", "MA", "PI") else "minima"
    return _cache(f"{uf}_mun.geojson", f"{IBGE}/v3/malhas/estados/{uf}?formato=application/vnd.geo+json&intrarregiao=municipio&qualidade={q}")


def nomes_uf(uf):
    """{código IBGE de 7 dígitos: nome do município}"""
    bruto = _cache(f"{uf.upper()}_nomes.json", f"{IBGE}/v1/localidades/estados/{uf.upper()}/municipios")
    return {str(m["id"]): m["nome"] for m in json.loads(bruto.decode("utf-8"))}
