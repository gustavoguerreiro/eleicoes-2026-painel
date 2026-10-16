#!/usr/bin/env python3
"""Painel da apuração 2026 (TSE): servidor web (padrão) e versão de terminal (1º turno).

Mostra, para o estado escolhido (padrão RN) e para o Brasil: presidente, governador, senador, deputado federal
e (no estado) deputado estadual; no 2º turno, o duelo de presidente e de governador ao vivo.

Uso:
    python painel_server.py --web                 # servidor em http://localhost:8765
    python painel_server.py --web --host 0.0.0.0  # acessível na rede (TV, celular); ver README para produção
    python painel_server.py --web --simular-2t    # TESTE: noite de eleição simulada (começa 18h55; --sim-inicio 17:00 p/ tudo)
    python painel_server.py --uma-vez             # terminal, 1º turno, imprime uma vez e sai

Só usa a biblioteca padrão do Python. Fonte: https://resultados.tse.jus.br/oficial (divulgação oficial).
"""
import argparse
import gzip
import hashlib
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = "https://resultados.tse.jus.br/oficial"
RAIZ = BASE + "/ele2026"
DATA_2T = "2026-10-25"
INICIO_DIVULGACAO_2T = "2026-10-25T19:00:00-03:00"   # a divulgação só começa depois do fim da votação no Acre
ELE_PRES, ELE_DEMAIS = "6257", "6259"          # presidente | governador, senador e deputados
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe", "pi", "pr",
       "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]
BRT = timezone(timedelta(hours=-3))
RAIZ_PROJETO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

log = logging.getLogger("painel")

if os.name == "nt":
    os.system("")                               # liga sequências ANSI no console do Windows
for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8")
V, R, A, C, D, N, Z = "[32m", "[31m", "[33m", "[36m", "[2m", "[1m", "[0m"


# ---- coleta -----------------------------------------------------------------------------------------------
ESTAT = dict(falhas=0, ultimo_ok=0.0)           # saúde da coleta: o painel avisa quando o dado está velho


def _requisitar(url, etag=None):
    """-> (status, json|None, etag). status: 200, 304 (igual ao que já temos), 404 (o arquivo ainda não existe) ou
    0 (falha passageira: rede, 403/429/5xx). Só o 404 significa "não existe"; o resto NUNCA pode virar "sem dados"."""
    for tentativa in range(3):
        espera = 0.5 * (tentativa + 1)
        try:
            cab = {"User-Agent": "Mozilla/5.0 eleicoes-2026-painel", "Accept-Encoding": "gzip"}
            if etag:
                cab["If-None-Match"] = etag
            with urllib.request.urlopen(urllib.request.Request(url, headers=cab), timeout=15) as r:
                corpo = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    corpo = gzip.decompress(corpo)
                ESTAT["ultimo_ok"] = time.time()
                return 200, json.loads(corpo.decode("utf-8-sig")), r.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304:
                ESTAT["ultimo_ok"] = time.time()
                return 304, None, etag
            if e.code == 404:
                ESTAT["ultimo_ok"] = time.time()
                return 404, None, None
            espera = 2.0 * (tentativa + 1) if e.code in (403, 429) else espera     # o TSE pediu calma
            log.warning("TSE respondeu %s em %s", e.code, url.rsplit("/", 1)[-1])
        except Exception as e:                                           # noqa: BLE001 - rede, JSON truncado...
            log.warning("falha ao baixar %s: %s", url.rsplit("/", 1)[-1], type(e).__name__)
        if tentativa < 2:
            time.sleep(espera)
    ESTAT["falhas"] += 1
    return 0, None, None


def _baixar_http(url):
    return _requisitar(url)[1]


def baixar(url):
    if SIM["ativo"]:                                   # --simular-2t: o 2º turno é fabricado a partir do 1º
        fab = simulado(url)
        if fab is not False:
            return fab
    return _baixar_http(url)


def url_u(ele, uf, cargo):
    return f"{RAIZ}/{ele}/dados/{uf}/{uf}-c{cargo:04d}-e{int(ele):06d}-u.json"


CACHE_URL, CACHE_TTL = {}, 0          # url -> {t, j, etag}; no modo web, o que foi baixado é reaproveitado por CACHE_TTL s


def baixar_cache(url):
    """Baixa com cache. Usa ETag (o TSE responde 304 quando nada mudou) e, se o TSE falhar, devolve o último dado bom
    em vez de "sem dados": uma falha de rede no meio da apuração não pode apagar a tela."""
    e, agora = CACHE_URL.get(url), time.time()
    if e and CACHE_TTL and agora - e["t"] < CACHE_TTL:
        return e["j"]
    if SIM["ativo"]:
        fab = simulado(url)
        if fab is not False:
            CACHE_URL[url] = dict(t=agora, j=fab, etag=None)
            return fab
    status, j, etag = _requisitar(url, e["etag"] if e else None)
    if status == 200:
        CACHE_URL[url] = dict(t=agora, j=j, etag=etag)
        return j
    if status == 304 and e:
        e["t"] = agora
        return e["j"]
    if status == 404:
        CACHE_URL[url] = dict(t=agora, j=None, etag=None)
        return None
    return e["j"] if e else None


def coletar(pedidos):
    """pedidos: lista de (ele, uf, cargo) -> dict {(uf, cargo): json|None}"""
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(lambda p: baixar_cache(url_u(*p)), pedidos))
    return {(p[1], p[2]): r for p, r in zip(pedidos, res)}


# ---- utilidades --------------------------------------------------------------------------------------------
def num(x):
    try:
        return float(str(x).replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def milhar(n):
    return f"{int(n):,}".replace(",", ".")


def pct(x):
    return f"{x:.2f}".replace(".", ",")


def candidatos(j):
    """Lista plana de candidatos do arquivo -u: dicts com nome, partido, votos, %, eleito."""
    out = []
    for cg in j.get("carg", []):
        for ag in cg.get("agr", []):
            for pa in ag.get("par", []):
                for c in pa.get("cand", []):
                    out.append(dict(nome=c.get("nmu") or c["nm"], n=str(c.get("n", "")), sg=pa.get("sg", ""), votos=num(c["vap"]),
                                    pct=num(c.get("pvap")), eleito=c.get("e") == "s" and "turno" not in c.get("st", "").lower(),
                                    t2=c.get("e") == "s" and "turno" in c.get("st", "").lower(), valido=c.get("dvt", "V").startswith("V"),    # arquivo ainda zerado não traz `dvt`
                                    agr=ag.get("com", ag.get("nm", ""))))
    return sorted(out, key=lambda c: -c["votos"])


def apurado(j):
    s = j.get("s") or {}
    return num(s["pstn"] if "pstn" in s else s.get("pst", 0))


def restantes(j):
    """Votos válidos ainda por apurar, projetados pelo % de seções apuradas."""
    p = apurado(j)
    vv = num(j["v"]["vv"])
    return vv * (100 - p) / p if p > 0 else float("inf")


def cab(titulo, j):
    if j is None:
        return f"{N}{titulo}{Z}  {D}(sem dados ainda){Z}"
    return f"{N}{titulo}{Z}  {D}{pct(apurado(j))}% das seções · atualizado {j.get('ht', '')}{Z}"


# ---- majoritários ------------------------------------------------------------------------------------------
def linha_cand(c, marca=""):
    return f"  {marca:<3}{c['nome'][:34]:<35}{c['sg']:<14}{milhar(c['votos']):>12}  {pct(c['pct']):>6}%"


def mostrar_1turno(titulo, j, mostrar=5):
    """Presidente/governador: maioria absoluta dos votos válidos no 1º turno, senão 2º turno."""
    print(cab(titulo, j))
    if j is None:
        return
    cs = [c for c in candidatos(j) if c["valido"]][:mostrar]
    if not cs:
        return
    lider, seg = cs[0], (cs[1] if len(cs) > 1 else None)
    for c in cs:
        print(linha_cand(c, "★" if c["eleito"] else "②" if c["t2"] else ""))
    vv, r = num(j["v"]["vv"]), restantes(j)
    total = vv + r
    teto = (lider["votos"] + r) / total * 100 if total else 0           # se o líder levasse TODO o restante
    if lider["t2"]:
        print(f"  {A}{N}2º TURNO (confirmado pelo TSE){Z}{A}: {lider['nome']} x {seg['nome'] if seg else '?'}{Z}")
    elif lider["eleito"]:
        print(f"  {V}{N}ELEITO NO 1º TURNO: {lider['nome']}{Z}")
    elif lider["pct"] > 50:
        print(f"  {V}{lider['nome']} acima de 50% dos válidos → tendência de eleição no 1º turno{Z}")
    elif teto <= 50:
        print(f"  {A}{N}2º TURNO CONFIRMADO{Z}{A}: {lider['nome']} x {seg['nome'] if seg else '?'} "
              f"(líder não alcança 50% nem com todo o restante){Z}")
    elif apurado(j) >= 99.99:
        print(f"  {A}{N}2º TURNO{Z}{A}: {lider['nome']} x {seg['nome'] if seg else '?'}{Z}")
    else:
        print(f"  {A}Tendência de 2º TURNO: {lider['nome']} x {seg['nome'] if seg else '?'} "
              f"(líder abaixo de 50%; precisaria de {pct(50 - lider['pct'])} p.p. a mais){Z}")


def mostrar_senado(titulo, j, mostrar=6):
    print(cab(titulo, j))
    if j is None:
        return
    nv = int(j["carg"][0]["nv"])
    cs = [c for c in candidatos(j) if c["valido"]]
    r = restantes(j)
    for i, c in enumerate(cs[:max(mostrar, nv + 2)]):
        dentro = i < nv or c["eleito"]
        print(linha_cand(c, ("★" if c["eleito"] else "▶") if dentro else ""))
    if len(cs) > nv:
        folga = cs[nv - 1]["votos"] - cs[nv]["votos"]
        if all(c["eleito"] for c in cs[:nv]):
            print(f"  {V}{N}ELEITOS: {' e '.join(c['nome'] for c in cs[:nv])}{Z}")
        else:
            cor = V if folga > 0.25 * r else A
            aviso = "folga confortável" if folga > 0.25 * r else "DISPUTA ABERTA"
            print(f"  {cor}Se encerrasse agora: {' e '.join(c['nome'] for c in cs[:nv])} "
                  f"(vaga {nv}ª vs {nv + 1}ª: {milhar(folga)} votos de diferença — {aviso}){Z}")


# ---- proporcionais -----------------------------------------------------------------------------------------
def projetar_cadeiras(j):
    """Distribuição das vagas (Lei 14.211): QE, quociente partidário (partido ≥80% do QE, candidato ≥20% do QE)
    e sobras por maior média. É uma PROJEÇÃO com os votos apurados até agora; o resultado oficial é o do TSE."""
    cg = j["carg"][0]
    nv = int(cg["nv"])
    vv = num(j["v"]["vv"])
    qe = vv / nv if nv else 0
    listas = []
    for ag in cg.get("agr", []):
        cands, legenda = [], 0.0
        for pa in ag.get("par", []):
            legenda += num(pa.get("tvtl"))
            for c in pa.get("cand", []):
                if c.get("dvt", "").startswith("V"):
                    cands.append(dict(nome=c.get("nmu") or c["nm"], sg=pa.get("sg", ""), votos=num(c["vap"]),
                                      eleito_tse=c.get("e") == "s"))
        cands.sort(key=lambda c: -c["votos"])
        votos = legenda + sum(c["votos"] for c in cands)
        listas.append(dict(nome=ag.get("com") or ag.get("nm"), votos=votos, cands=cands, eleitos=[]))
    # 1ª fase: quociente partidário
    for l in listas:
        if qe and l["votos"] >= 0.8 * qe:
            qp = int(l["votos"] // qe)
            aptos = [c for c in l["cands"] if c["votos"] >= 0.2 * qe]
            l["eleitos"] = aptos[:qp]
    # 2ª fase: sobras por maior média (todos os partidos concorrem, conforme decisão do STF de 2024)
    restam = nv - sum(len(l["eleitos"]) for l in listas)
    for _ in range(max(restam, 0)):
        livres = [l for l in listas if len(l["eleitos"]) < len(l["cands"])]
        if not livres:
            break
        l = max(livres, key=lambda l: l["votos"] / (len(l["eleitos"]) + 1))
        prox = next(c for c in l["cands"] if c not in l["eleitos"])
        l["eleitos"].append(prox)
    eleitos = [dict(c, lista=l["nome"]) for l in listas for c in l["eleitos"]]
    return nv, qe, sorted(eleitos, key=lambda c: -c["votos"]), listas


def mostrar_proporcional(titulo, j):
    print(cab(titulo, j))
    if j is None:
        return
    nv, qe, eleitos, listas = projetar_cadeiras(j)
    print(f"  {D}{nv} vagas · quociente eleitoral {milhar(qe)} · projeção com os votos apurados até agora{Z}")
    for c in eleitos:
        marca = "★" if c["eleito_tse"] else "▶"
        print(f"  {marca:<3}{c['nome'][:34]:<35}{c['sg']:<9}{c['lista'][:22]:<23}{milhar(c['votos']):>10}")
    bancada = {}
    for c in eleitos:
        bancada[c["lista"]] = bancada.get(c["lista"], 0) + 1
    print(f"  {C}Bancadas: " + " · ".join(f"{k} {v}" for k, v in sorted(bancada.items(), key=lambda x: -x[1])) + Z)
    print(f"  {D}★ = marcado como eleito pelo TSE · ▶ = se elegeria com os votos de agora{Z}")


# ---- Brasil ------------------------------------------------------------------------------------------------
def mostrar_brasil(dados, jpres):
    mostrar_1turno("PRESIDENTE — BRASIL", jpres, mostrar=5)
    print()
    print(f"{N}GOVERNADORES — todos os estados{Z}  {D}(líder · % dos válidos · situação){Z}")
    for uf in UFS:
        j = dados.get((uf, 3))
        if not j:
            print(f"  {uf.upper()}  {D}sem dados{Z}")
            continue
        cs = [c for c in candidatos(j) if c["valido"]]
        if not cs:
            continue
        l = cs[0]
        r = restantes(j)
        teto = (l["votos"] + r) / (num(j["v"]["vv"]) + r) * 100
        if l["eleito"]:
            sit = f"{V}ELEITO{Z}"
        elif l["pct"] > 50:
            sit = f"{V}1º turno (tendência){Z}"
        elif teto <= 50 or apurado(j) >= 99.99:
            sit = f"{A}{N}2º TURNO{Z} {A}x {cs[1]['nome'][:22] if len(cs) > 1 else '?'}{Z}"
        else:
            sit = f"{A}tend. 2º turno x {cs[1]['nome'][:22] if len(cs) > 1 else '?'}{Z}"
        print(f"  {uf.upper()}  {l['nome'][:26]:<27}{l['sg']:<10}{pct(l['pct']):>6}%  {pct(apurado(j)):>6}% apur.  {sit}")
    print()
    print(f"{N}SENADORES — 2 vagas por estado{Z}  {D}(os 2 mais votados agora){Z}")
    for uf in UFS:
        j = dados.get((uf, 5))
        if not j:
            print(f"  {uf.upper()}  {D}sem dados{Z}")
            continue
        cs = [c for c in candidatos(j) if c["valido"]]
        nv = int(j["carg"][0]["nv"])
        txt = " · ".join(f"{c['nome'][:22]} ({c['sg']}) {pct(c['pct'])}%" for c in cs[:nv])
        sel = f"{V}★{Z}" if all(c["eleito"] for c in cs[:nv]) else f"{D}▶{Z}"
        print(f"  {uf.upper()}  {sel} {txt}  {D}[{pct(apurado(j))}% apur.]{Z}")
    print()
    print(f"{N}DEPUTADOS FEDERAIS — projeção da Câmara (513){Z}  {D}(soma das projeções por estado){Z}")
    bancada, vagas, faltam = {}, 0, []
    for uf in UFS:
        j = dados.get((uf, 6))
        if not j:
            faltam.append(uf.upper())
            continue
        nv, _, eleitos, _ = projetar_cadeiras(j)
        vagas += nv
        for c in eleitos:
            bancada[c["sg"]] = bancada.get(c["sg"], 0) + 1
    if bancada:
        ordem = sorted(bancada.items(), key=lambda x: -x[1])
        print("  " + " · ".join(f"{k} {v}" for k, v in ordem))
        print(f"  {D}{vagas} vagas projetadas" + (f" · sem dados: {', '.join(faltam)}" if faltam else "") + Z)


# ---- laço principal ----------------------------------------------------------------------------------------
def desenhar(uf, so_uf, so_br):
    pedidos = [(ELE_PRES, "br", 1)]
    if not so_uf:
        pedidos += [(ELE_DEMAIS, u, c) for u in UFS for c in (3, 5, 6)]
    if not so_br:
        pedidos += [(ELE_DEMAIS, uf, c) for c in (3, 5, 6, 8 if uf == "df" else 7)]
    dados = coletar(list(dict.fromkeys(pedidos)))
    jpres = dados.get(("br", 1))
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M:%S")
    linhas = [f"{N}APURAÇÃO 2026 — TSE (oficial){Z}   {D}consulta às {agora} (Brasília){Z}", ""]
    return dados, jpres, linhas


def renderizar(uf, so_uf, so_br):
    dados, jpres, linhas = desenhar(uf, so_uf, so_br)
    print("\n".join(linhas))
    if not so_br:
        print(f"{N}{C}════════ {uf.upper()} ════════{Z}")
        mostrar_1turno(f"GOVERNADOR — {uf.upper()}", dados.get((uf, 3)))
        print()
        mostrar_senado(f"SENADOR — {uf.upper()} (2 vagas)", dados.get((uf, 5)))
        print()
        mostrar_proporcional(f"DEPUTADO FEDERAL — {uf.upper()}", dados.get((uf, 6)))
        print()
        mostrar_proporcional(f"DEPUTADO {'DISTRITAL' if uf == 'df' else 'ESTADUAL'} — {uf.upper()}",
                             dados.get((uf, 8 if uf == "df" else 7)))
        print()
    if not so_uf:
        print(f"{N}{C}════════ BRASIL ════════{Z}")
        mostrar_brasil(dados, jpres)


# ---- modo navegador ----------------------------------------------------------------------------------------
def situacao_1turno(j, cs):
    """(tipo, rótulo, texto) para presidente/governador: maioria absoluta dos válidos no 1º turno, senão 2º turno."""
    if not cs:
        return None
    lider, seg = cs[0], (cs[1] if len(cs) > 1 else None)
    r = restantes(j)
    teto = (lider["votos"] + r) / (num(j["v"]["vv"]) + r) * 100
    vs = f"{lider['nome']} x {seg['nome']}" if seg else lider["nome"]
    if lider["t2"]:
        return dict(tipo="2turno", rotulo="2º TURNO (confirmado pelo TSE)", texto=vs)
    if lider["eleito"]:
        return dict(tipo="eleito", rotulo="ELEITO NO 1º TURNO", texto=f"{lider['nome']} (confirmado pelo TSE)")
    if lider["pct"] > 50:
        return dict(tipo="1turno", rotulo="1º TURNO (tendência)", texto=f"{lider['nome']} está acima de 50% dos votos válidos")
    if teto <= 50:
        return dict(tipo="2turno", rotulo="2º TURNO CONFIRMADO",
                    texto=f"{vs} — o líder não chega a 50% nem levando todo o restante")
    if apurado(j) >= 99.99:
        return dict(tipo="2turno", rotulo="2º TURNO", texto=vs)
    return dict(tipo="2turno", rotulo="TENDÊNCIA DE 2º TURNO",
                texto=f"{vs} — líder abaixo de 50% (faltam {pct(50 - lider['pct'])} p.p.)")


def web_majoritario(j, mostrar=5):
    if not j:
        return None
    cs = [c for c in candidatos(j) if c["valido"]]
    return dict(apur=apurado(j), ht=j.get("ht", ""), situacao=situacao_1turno(j, cs),
                cands=[{k: c[k] for k in ("nome", "sg", "votos", "pct", "eleito", "t2")} for c in cs[:mostrar]])


def web_senado(j):
    if not j:
        return None
    cs = [c for c in candidatos(j) if c["valido"]]
    nv, r = int(j["carg"][0]["nv"]), restantes(j)
    if all(c["eleito"] for c in cs[:nv]):
        sit = dict(tipo="eleito", rotulo="ELEITOS", texto=" e ".join(c["nome"] for c in cs[:nv]))
    else:
        folga = cs[nv - 1]["votos"] - cs[nv]["votos"] if len(cs) > nv else 0
        firme = folga > 0.25 * r
        sit = dict(tipo="1turno" if firme else "aberto", rotulo="FOLGA" if firme else "DISPUTA ABERTA",
                   texto=f"Se encerrasse agora: {' e '.join(c['nome'] for c in cs[:nv])}. "
                         f"{nv}ª vs {nv + 1}ª vaga: {milhar(folga)} votos de diferença.")
    return dict(apur=apurado(j), ht=j.get("ht", ""), nv=nv, situacao=sit,
                cands=[{k: c[k] for k in ("nome", "sg", "votos", "pct", "eleito", "t2")} for c in cs[:max(6, nv + 2)]])


def web_proporcional(j, fora=3):
    if not j:
        return None
    nv, qe, eleitos, listas = projetar_cadeiras(j)
    chaves = {(c["nome"], c["votos"]) for c in eleitos}
    resto = sorted((dict(c, lista=l["nome"]) for l in listas for c in l["cands"]
                    if (c["nome"], c["votos"]) not in chaves), key=lambda c: -c["votos"])[:fora]
    band = {}
    for c in eleitos:
        band[c["lista"]] = band.get(c["lista"], 0) + 1
    return dict(apur=apurado(j), ht=j.get("ht", ""), nv=nv, qe=qe,
                eleitos=[dict(nome=c["nome"], sg=c["sg"], votos=c["votos"], tse=c["eleito_tse"]) for c in eleitos],
                fora=[dict(nome=c["nome"], sg=c["sg"], votos=c["votos"]) for c in resto],
                bancadas=sorted(band.items(), key=lambda x: -x[1]))


# ---- mapas -------------------------------------------------------------------------------------------------
def resumo_mapa(j, n=3):
    """Os n mais votados de um arquivo -u, para pintar/descrever uma região no mapa."""
    if not j:
        return None
    cs = [c for c in candidatos(j) if c["valido"]][:n]
    return dict(apur=apurado(j), cands=[{k: c[k] for k in ("nome", "sg", "votos", "pct")} for c in cs])


_MUN = {}                                                          # {uf: [(cód TSE, cód IBGE, nome)]}


def municipios_tse():
    """Códigos de município do TSE e do IBGE (campo `cdi`), do cm.json da divulgação."""
    if not _MUN:
        j = baixar(f"{RAIZ}/{ELE_PRES}/config/mun-e{int(ELE_PRES):06d}-cm.json")
        for a in (j or {}).get("abr", []):
            _MUN[a["cd"]] = [(m["cd"], m["cdi"], m["nm"]) for m in a.get("mu", [])]
    return _MUN


def mapa_municipios(uf, cargo, turno=1):
    """Resultado de cada município da UF para o cargo (1 presidente, 3 governador, 5 senador).
    turno=2: o 2º turno ao vivo, se já houver arquivos; antes disso, o desempenho dos dois finalistas no 1º turno."""
    import geo
    cod = codigos_turno()
    ele1 = cod["pres1"] if cargo == 1 else cod["dem1"]
    ele2 = cod["pres2"] if cargo == 1 else cod["dem2"]
    muns = municipios_tse().get(uf, [])
    nomes = {}
    try:
        nomes = geo.nomes_uf(uf)
    except Exception:
        pass

    def urls(ele):
        return [f"{RAIZ}/{ele}/dados/{uf}/{uf}{tse}-c{cargo:04d}-e{int(ele):06d}-u.json" for tse, _, _ in muns]

    def baixa(us):
        with ThreadPoolExecutor(max_workers=16) as ex:
            return list(ex.map(baixar_cache, us))

    r1 = baixa(urls(ele1))
    modo, r2 = "1t", [None] * len(muns)
    finalistas = set()
    if turno == 2:
        uf1 = baixar_cache(url_u(ele1, uf, cargo))
        finalistas = {c["n"] for c in finalistas_1t(uf1)} if uf1 else set()
        if t2_disponivel():
            r2 = baixa(urls(ele2))
            modo = "2t"
        else:
            modo = "duelo_1t"
    out = {}
    for (tse, ibge, nm), j1, j2 in zip(muns, r1, r2):
        if turno == 2 and modo == "2t":
            r = resumo_mapa(j2, 2) if j2 and apurado(j2) > 0 else None
        elif turno == 2:
            r = resumo_duelo(j1, finalistas)
        else:
            r = resumo_mapa(j1)
        if r:
            out[ibge] = dict(r, nome=nomes.get(ibge) or nm.title())
    return dict(uf=uf.upper(), cargo=cargo, turno=turno, modo=modo, total=len(muns), municipios=out)


def dados_web(uf, so_uf, so_br):
    pedidos = [(ELE_PRES, "br", 1)]
    if not so_uf:
        pedidos += [(ELE_DEMAIS, u, c) for u in UFS for c in (3, 5, 6)]
        pedidos += [(ELE_PRES, u, 1) for u in UFS]
    pedidos += [(ELE_DEMAIS, uf, c) for c in (3, 5, 6, 8 if uf == "df" else 7)]
    dados = coletar(list(dict.fromkeys(pedidos)))
    out = dict(turno=1, meta=meta(), agora=datetime.now(BRT).strftime("%H:%M:%S"), pres=web_majoritario(dados.get(("br", 1))))
    out["uf"] = dict(sigla=uf.upper(), gov=web_majoritario(dados.get((uf, 3))), sen=web_senado(dados.get((uf, 5))),
                     fed=web_proporcional(dados.get((uf, 6))),
                     est=web_proporcional(dados.get((uf, 8 if uf == "df" else 7))))
    if so_uf:
        return out
    gov_br, sen_br, bancada, vagas, faltam, band_sen, sen_tse = [], [], {}, 0, [], {}, 0
    for u in UFS:
        j = dados.get((u, 3))
        cs = [c for c in candidatos(j) if c["valido"]] if j else []
        if cs:
            s = situacao_1turno(j, cs)
            gov_br.append(dict(uf=u.upper(), nome=cs[0]["nome"], sg=cs[0]["sg"], pct=cs[0]["pct"], votos=cs[0]["votos"],
                               seg=cs[1]["nome"] if len(cs) > 1 else "", apur=apurado(j), tipo=s["tipo"],
                               rotulo={"eleito": "ELEITO", "1turno": "1º turno", "2turno": "2º TURNO"}[s["tipo"]]))
        j = dados.get((u, 5))
        cs = [c for c in candidatos(j) if c["valido"]] if j else []
        if cs:
            nv = int(j["carg"][0]["nv"])
            top = cs[:nv]
            for c in top:
                band_sen[c["sg"]] = band_sen.get(c["sg"], 0) + 1
                sen_tse += c["eleito"]
            sen_br.append(dict(uf=u.upper(), apur=apurado(j), tse=all(c["eleito"] for c in top),
                               sig=",".join(f"{c['nome']}{c['votos']:.0f}" for c in top),
                               eleitos=[{k: c[k] for k in ("nome", "sg", "pct")} for c in top]))
        j = dados.get((u, 6))
        if j:
            nv, _, eleitos, _ = projetar_cadeiras(j)
            vagas += nv
            for c in eleitos:
                bancada[c["sg"]] = bancada.get(c["sg"], 0) + 1
        else:
            faltam.append(u.upper())
    out["mapa_br"] = {u.upper(): {str(c): resumo_mapa(dados.get((u, c))) for c in (1, 3, 5)} for u in UFS}
    out.update(gov_br=gov_br, sen_br=sen_br,
               camara=dict(partidos=sorted(bancada.items(), key=lambda x: -x[1]), vagas=vagas, faltam=faltam),
               senado=dict(partidos=sorted(band_sen.items(), key=lambda x: -x[1]), tse=sen_tse))
    return out


# ---- 2º turno ----------------------------------------------------------------------------------------------
_COD = dict(t=0.0, v=None)


def codigos_turno():
    """Códigos de eleição do 1º e do 2º turno (campo `cdt2` do ele-c.json). Se falhar, usa os já anunciados."""
    if _COD["v"] and time.time() - _COD["t"] < 600:
        return _COD["v"]
    v = dict(pres1=ELE_PRES, pres2="6258", dem1=ELE_DEMAIS, dem2="6260")
    j = _baixar_http(f"{BASE}/comum/config/ele-c.json") or {}
    for pl in j.get("pl", []):
        if "2026" not in str(pl.get("c", "")):
            continue
        for e in pl.get("e", []):
            if str(e.get("t")) != "1":
                continue
            for a in e.get("abr", []):
                for cp in a.get("cp", []):
                    if a.get("cd") == "br" and cp.get("cd") == "1":
                        v.update(pres1=e["cd"], pres2=e.get("cdt2") or v["pres2"])
                    if a.get("cd") == "br" and cp.get("cd") == "3":
                        v.update(dem1=e["cd"], dem2=e.get("cdt2") or v["dem2"])
    _COD.update(t=time.time() if j else time.time() - 540, v=v)      # sem resposta: tenta de novo em 1 min
    return v


_AO_VIVO = dict(v=False)


def t2_disponivel():
    """O 2º turno já tem votos apurados? O TSE publica os arquivos zerados dias antes (existir NÃO basta) e, depois que
    a apuração começa, o estado nunca volta atrás: uma falha passageira não pode devolver a tela ao "aguardando"."""
    if _AO_VIVO["v"]:
        return True
    j = baixar_cache(url_u(codigos_turno()["pres2"], "br", 1))
    if j and apurado(j) > 0:
        _AO_VIVO["v"] = True
    return _AO_VIVO["v"]


def meta():
    m = dict(t2_disponivel=t2_disponivel(), simulado=SIM["ativo"], data_2t=DATA_2T, inicio_2t=INICIO_DIVULGACAO_2T)
    if SIM["ativo"]:                                   # a contagem regressiva e o relógio seguem o tempo simulado
        agora = minuto_sim()
        seg_por_min = SIM["duracao"] / (SIM_FIM_MIN - SIM_INICIO_MIN)
        falta = max(0.0, SIM_ABERTURA_MIN - agora) * seg_por_min
        m["inicio_2t"] = (datetime.now(BRT) + timedelta(seconds=falta)).isoformat(timespec="seconds")
        m["relogio_sim"] = hhmm_sim(int(agora))
    return m


# ---- simulador do 2º turno (--simular-2t) -------------------------------------------------------------------
# Um relógio simulado vai de 17h a 22h em SIM["duracao"] segundos reais. Os arquivos zerados duram até as 19h (a divulgação
# só começa depois do fim da votação no Acre); depois cada arquivo (estado, município) começa e termina de ser contado em
# momentos diferentes, rápido no começo e devagar no fim, e o primeiro colocado do 1º turno aparece inflado no início
# (as primeiras seções costumam favorecer um lado). O arquivo do Brasil é a SOMA dos 27 estados, como no TSE.
SIM = dict(ativo=False, t0=0.0, duracao=300.0)
SIM_INICIO_MIN, SIM_ABERTURA_MIN, SIM_FIM_MIN = 17 * 60, 19 * 60, 22 * 60
SIM_LEAN = 0.40            # fatia dos votos dos eliminados que vai para o 1º colocado do 1º turno: deixa a disputa apertada
_SIM_1T = {}


def minuto_sim():
    """Minuto do dia no relógio simulado (fracionário)."""
    prog = min(1.0, max(0.0, (time.time() - SIM["t0"]) / SIM["duracao"]))
    return SIM_INICIO_MIN + prog * (SIM_FIM_MIN - SIM_INICIO_MIN)


def hhmm_sim(minuto):
    return f"{minuto // 60:02d}:{minuto % 60:02d}"


def _1t_fixo(url):
    """No simulador o 1º turno não muda: baixa uma vez só (não martela o TSE a cada segundo)."""
    if url not in _SIM_1T:
        j = _baixar_http(url)
        if j is None:
            return None
        _SIM_1T[url] = j
    return _SIM_1T[url]


def simulado(url):
    """Devolve um arquivo de 2º turno fabricado a partir do equivalente do 1º (False = não é um arquivo de 2º turno)."""
    c = codigos_turno()
    for k1, k2 in (("pres1", "pres2"), ("dem1", "dem2")):
        e1, e2 = c[k1], c[k2]
        if f"/{e2}/" in url and f"e{int(e2):06d}" in url:
            j1 = _1t_fixo(url.replace(f"/{e2}/", f"/{e1}/").replace(f"e{int(e2):06d}", f"e{int(e1):06d}"))
            if not j1:
                return None
            if k1 == "pres1" and "/br/br-" in url:
                return sintetizar_br(j1)
            nums = None
            if k1 == "pres1":                           # nos estados do presidente, os finalistas são os do Brasil
                jbr = _1t_fixo(url_u(e1, "br", 1))
                nums = {x["n"] for x in finalistas_1t(jbr)} if jbr else None
            return sintetizar_2t(j1, url, nums)
    return False


def _andamento(rnd, minuto):
    """Fração das seções apuradas de UM arquivo no minuto dado: começa entre 19h08 e 19h30, leva de 40 a 150 min."""
    inicio, dur = 8 + rnd.random() * 22, 40 + rnd.random() * 110
    x = min(1.0, max(0.0, (minuto - SIM_ABERTURA_MIN - inicio) / dur))
    return 1 - (1 - x) ** 2


def sintetizar_2t(j1, url, nums=None):
    """Arquivo de um estado/município: os dois finalistas ficam com os votos do 1º turno + uma divisão estável dos votos dos
    eliminados. Votos contados = final × (andamento ± viés inicial); no fim (andamento 1) o viés some e o total é exato."""
    import hashlib
    import random
    rnd = random.Random(int(hashlib.md5(url.encode()).hexdigest(), 16) % 2 ** 32)
    cs = [c for c in candidatos(j1) if c["valido"]]
    fin = ([c for c in cs if c["n"] in nums] if nums else ([c for c in cs if c["t2"]] or cs))[:2]
    if len(fin) < 2:
        return None
    minuto = int(minuto_sim())
    local = _andamento(rnd, minuto)
    lean = min(0.9, max(0.1, SIM_LEAN + (rnd.random() - 0.5) * 0.3))
    beta = 0.10 + (rnd.random() - 0.5) * 0.12
    outros = sum(c["votos"] for c in cs if c["n"] not in {f["n"] for f in fin})
    desvio = beta * local * (1 - local)                      # nunca decresce: a contagem só acumula
    novos = {fin[0]["n"]: round((fin[0]["votos"] + lean * outros) * (local + desvio)),
             fin[1]["n"]: round((fin[1]["votos"] + (1 - lean) * outros) * (local - desvio))}
    ts = int(num(j1["s"]["ts"]))
    return _montar_2t(j1, novos, round(ts * local), ts, minuto, local >= 1)


def sintetizar_br(j1):
    """O Brasil é a soma dos estados (votos e seções), como na divulgação real."""
    c = codigos_turno()
    nums = [x["n"] for x in finalistas_1t(j1)]
    soma, st, ts = {n: 0 for n in nums}, 0, 0
    for uf in UFS:
        ju1 = _1t_fixo(url_u(c["pres1"], uf, 1))
        ju = sintetizar_2t(ju1, url_u(c["pres2"], uf, 1), set(nums)) if ju1 else None
        if not ju:
            continue
        for x in candidatos(ju):
            if x["n"] in soma:
                soma[x["n"]] += x["votos"]
        st, ts = st + int(num(ju["s"]["st"])), ts + int(num(ju["s"]["ts"]))
    if not ts:
        return None
    return _montar_2t(j1, {n: round(v) for n, v in soma.items()}, st, ts, int(minuto_sim()), st >= ts)


def _montar_2t(j1, novos, st, ts, minuto, completo):
    import copy
    total = sum(novos.values())
    fmt = lambda x: f"{x:.2f}".replace(".", ",")
    pc = st / ts * 100 if ts else 0.0
    j = copy.deepcopy(j1)
    for cg in j.get("carg", []):
        agrs = []
        for ag in cg.get("agr", []):
            pars = []
            for pa in ag.get("par", []):
                pa["cand"] = [c for c in pa.get("cand", []) if str(c.get("n")) in novos]
                for c in pa["cand"]:
                    v = novos[str(c["n"])]
                    p = v / total * 100 if total else 0.0
                    c.update(vap=str(v), pvap=fmt(p), pvapn=f"{p:.9f}".replace(".", ","), dvt="Válido")
                    venceu = completo and v == max(novos.values())
                    c.update(e="s" if venceu else "n", st=("Eleito" if venceu else "Não eleito") if completo else "")
                if pa["cand"]:
                    pars.append(pa)
            if pars:
                ag["par"] = pars
                agrs.append(ag)
        cg["agr"] = agrs
    j["s"].update(ts=str(ts), st=str(st), pst=fmt(pc), pstn=f"{pc:.9f}".replace(".", ","))
    j["v"].update(vv=str(total), vvc=str(total))
    j["t"] = "2"
    dia = datetime.now(BRT)
    j["dg"], j["hg"], j["ht"] = dia.strftime("%d/%m/%Y"), hhmm_sim(minuto) + ":00", hhmm_sim(minuto) + ":00"
    return j


def finalistas_1t(j1):
    """Os dois candidatos que foram ao 2º turno (marcados pelo TSE) ou, se ainda não marcou, os dois mais votados."""
    cs = [c for c in candidatos(j1) if c["valido"]]
    return ([c for c in cs if c["t2"]] or cs[:2])[:2]


def resumo_duelo(j1, nums):
    """Antes do 2º turno: só os dois finalistas, com os votos que tiveram no 1º turno naquela região."""
    if not j1:
        return None
    cs = [c for c in candidatos(j1) if c["valido"] and c["n"] in nums]
    if len(cs) < 2:
        return None
    return dict(apur=apurado(j1), cands=[{k: c[k] for k in ("nome", "sg", "votos", "pct")} for c in cs])


def base_1t(j1, nums):
    """O que o 1º turno deixou 'em disputa' para o 2º: eleitores dos eliminados, brancos, nulos e abstenção."""
    cs = [c for c in candidatos(j1) if c["valido"]]
    elim = [c for c in cs if c["n"] not in nums]
    vv = num(j1["v"]["vv"])
    e, v = j1.get("e", {}), j1.get("v", {})
    outros = sum(c["votos"] for c in elim)
    return dict(apur=apurado(j1), validos=vv, outros_votos=outros, outros_pct=outros / vv * 100 if vv else 0,
                brancos=num(v.get("vb")), nulos=num(v.get("tvn")), abstencao=num(e.get("a")), aptos=num(e.get("te")),
                comparecimento_pct=num(e.get("pc")),
                eliminados=[{k: c[k] for k in ("nome", "sg", "votos", "pct")} for c in elim[:8]])


def situacao_2t(j, cs):
    """No 2º turno vence quem tiver mais votos válidos. A "vitória projetada" só aparece quando a diferença supera, com
    folga de 30%, tudo o que falta apurar, e só depois de 30% das seções: o que falta é uma estimativa (seções têm
    tamanhos e perfis diferentes). Quem encerra a disputa é o TSE (`eleito`)."""
    if len(cs) < 2 or apurado(j) <= 0:
        return dict(tipo="aberto", rotulo="AGUARDANDO APURAÇÃO", texto="Os primeiros resultados ainda não chegaram.")
    a, b = cs[0], cs[1]
    dif, r = a["votos"] - b["votos"], restantes(j)
    if a["eleito"]:
        return dict(tipo="eleito", rotulo="ELEITO", texto=f"{a['nome']} (confirmado pelo TSE)")
    if apurado(j) >= 30 and dif > 1.3 * r:
        return dict(tipo="1turno", rotulo="VITÓRIA PROJETADA",
                    texto=f"{a['nome']} lidera por {milhar(dif)} votos, mais do que o que falta apurar. Aguarda confirmação do TSE")
    falta = (f"{r / 1e6:.1f}".replace(".", ",") + " milhões de votos válidos") if r >= 1e6 else f"{milhar(r)} votos válidos"
    return dict(tipo="aberto", rotulo="DISPUTA ABERTA",
                texto=f"{a['nome']} tem {milhar(dif)} votos a mais. Faltam cerca de {falta}.")


class Historico:
    """Evolução do duelo ao longo da apuração (um ponto por atualização do TSE), para o gráfico de linhas.
    Fica em disco (logs/historico_2t.json) para sobreviver a um reinício na noite da eleição; não grava na simulação."""

    def __init__(self, arquivo=None, maximo=720):
        self.maximo, self.trava = maximo, threading.Lock()
        self.abrir(arquivo)

    def abrir(self, arquivo):
        self.arquivo, self.series = arquivo, {}
        if arquivo and os.path.exists(arquivo):
            try:
                with open(arquivo, encoding="utf-8") as f:
                    self.series = json.load(f)
            except (OSError, ValueError):
                self.series = {}

    def registrar(self, chave, j):
        cs = [c for c in candidatos(j) if c["valido"]][:2] if j else []
        if len(cs) < 2 or apurado(j) <= 0:
            return
        ponto = dict(h=j.get("ht") or datetime.now(BRT).strftime("%H:%M:%S"), a=round(apurado(j), 2),
                     v={c["n"]: int(c["votos"]) for c in cs})
        with self.trava:
            lista = self.series.setdefault(chave, [])
            if lista and lista[-1]["a"] == ponto["a"] and lista[-1]["v"] == ponto["v"]:
                return
            lista.append(ponto)
            del lista[:-self.maximo]
            if self.arquivo:
                try:
                    os.makedirs(os.path.dirname(self.arquivo), exist_ok=True)
                    with open(self.arquivo, "w", encoding="utf-8") as f:
                        json.dump(self.series, f)
                except OSError:
                    pass

    def serie(self, chave):
        with self.trava:
            return list(self.series.get(chave, []))


HIST = Historico()


def web_2t(j2, j1, serie=None):
    """Cartão do duelo. Ao vivo (j2) mostra o 2º turno; antes dele, os finalistas com o desempenho do 1º turno (j1)."""
    if not j1:
        return None
    fin = finalistas_1t(j1)
    nums = {c["n"] for c in fin}
    ref = {c["n"]: c["pct"] for c in fin}
    refv = {c["n"]: c["votos"] for c in fin}
    base = base_1t(j1, nums)
    campos = ("nome", "n", "sg", "votos", "pct", "eleito")
    if j2 and apurado(j2) > 0:
        cs = [c for c in candidatos(j2) if c["valido"]][:2]
        return dict(ao_vivo=True, apur=apurado(j2), ht=j2.get("ht", ""), situacao=situacao_2t(j2, cs), base=base,
                    serie=serie or [],
                    cands=[dict({k: c[k] for k in campos}, pct1t=ref.get(c["n"], 0), votos1t=refv.get(c["n"], 0)) for c in cs])
    return dict(ao_vivo=False, apur=0, ht=j1.get("ht", ""), base=base, serie=[],
                situacao=dict(tipo="aberto", rotulo="AGUARDANDO O 2º TURNO", texto=f"A votação é em {DATA_2T[8:]}/{DATA_2T[5:7]}. Abaixo, como cada um foi no 1º turno."),
                cands=[dict({k: c[k] for k in campos}, pct1t=c["pct"], votos1t=c["votos"]) for c in fin])


def dados_2t(uf):
    c = codigos_turno()
    ok = t2_disponivel()
    d1 = coletar([(c["pres1"], "br", 1)] + [(c["pres1"], u, 1) for u in UFS] + [(c["dem1"], uf, 3)])
    d2 = coletar([(c["pres2"], "br", 1)] + [(c["pres2"], u, 1) for u in UFS] + [(c["dem2"], uf, 3)]) if ok else {}
    if ok:
        HIST.registrar("BR", d2.get(("br", 1)))
        HIST.registrar(uf.upper(), d2.get((uf, 3)))
    out = dict(turno=2, meta=meta(), agora=datetime.now(BRT).strftime("%H:%M:%S"),
               pres=web_2t(d2.get(("br", 1)), d1.get(("br", 1)), HIST.serie("BR")))
    fin_gov = finalistas_1t(d1[(uf, 3)]) if d1.get((uf, 3)) else []
    out["uf"] = dict(sigla=uf.upper(), em_2turno=bool(d1.get((uf, 3)) and any(x["t2"] for x in fin_gov)),
                     gov=web_2t(d2.get((uf, 3)), d1.get((uf, 3)), HIST.serie(uf.upper())))
    mapa = {}
    nums = {x["n"] for x in finalistas_1t(d1[("br", 1)])} if d1.get(("br", 1)) else set()
    for u in UFS:
        j2, j1 = d2.get((u, 1)), d1.get((u, 1))
        if ok:
            r = resumo_mapa(j2, 2) if j2 and apurado(j2) > 0 else None
        else:
            r = resumo_duelo(j1, nums)
        if r:
            mapa[u.upper()] = {"1": r}
    out["mapa_br"] = mapa
    return out


Pronto = namedtuple("Pronto", "js etag gz")        # corpo, ETag e versão gzip: calculados uma vez por renovação, não por requisição


def empacotar(js, etag=True):
    return Pronto(js, '"' + hashlib.md5(js).hexdigest()[:20] + '"' if etag else None,
                  gzip.compress(js, 5) if len(js) > 1024 else None)


class CacheVivo:
    """Respostas prontas na memória, renovadas em segundo plano: nenhuma requisição HTTP espera o TSE (só a primeira de
    cada chave) e várias abas/amigos não multiplicam as consultas. Se a renovação falhar, segue servindo a última boa.
    Chaves "fixas" são renovadas sempre (mesmo sem ninguém olhando); as demais, enquanto alguém as usa."""

    def __init__(self, intervalo, trabalhadores=3):
        self.intervalo, self.itens, self.trava = intervalo, {}, threading.Lock()
        self.pool = ThreadPoolExecutor(trabalhadores, thread_name_prefix="renovador")   # o mapa lento não atrasa o /api
        threading.Thread(target=self._laco, daemon=True, name="renovador-laco").start()

    def registrar(self, chave, fn, ttl=None, fixo=False):
        with self.trava:
            it = self.itens.setdefault(chave, dict(fn=fn, js=None, t=0.0, ttl=ttl or self.intervalo, lock=threading.Lock(),
                                                   pedido=0.0, retry=0.0, fixo=False, emvoo=False))
            it["fixo"] = it["fixo"] or fixo
            return it

    def obter(self, chave, fn, ttl=None):
        it = self.registrar(chave, fn, ttl)
        it["pedido"] = time.time()
        if it["js"] is None:                                       # primeira vez: uma só thread busca, as outras esperam
            self._renovar(it, chave)
        return it["js"]

    def idade_fixos(self):
        """Idade do dado mais velho entre as chaves fixas (None se ainda não houver nenhum)."""
        ts = [it["t"] for it in self.itens.values() if it["fixo"] and it["js"] is not None]
        return time.time() - min(ts) if ts else None

    def _renovar(self, it, chave):
        with it["lock"]:
            agora = time.time()
            if it["js"] is not None and agora - it["t"] < it["ttl"]:
                return
            if it["js"] is None and agora < it["retry"]:           # acabou de falhar: não empilha requisições na fila
                return
            try:
                it["js"], it["t"], it["retry"] = empacotar(it["fn"]()), time.time(), 0.0
            except Exception:                                      # noqa: BLE001 - o painel segue com o último dado bom
                log.exception("falha ao renovar %s", chave)
                it["retry"] = time.time() + 5
                it["t"] = time.time() - it["ttl"] + 5              # tenta de novo em ~5 s

    def _tarefa(self, it, chave):
        try:
            self._renovar(it, chave)
        finally:
            it["emvoo"] = False

    def _laco(self):
        while True:
            time.sleep(1)
            agora = time.time()
            for chave, it in list(self.itens.items()):
                if agora - it["t"] >= it["ttl"] and (it["fixo"] or agora - it["pedido"] < 900) and not it["emvoo"]:
                    it["emvoo"] = True
                    self.pool.submit(self._tarefa, it, chave)


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")


def hosts_permitidos(host_escuta, porta, extras=()):
    """Valores de `Host` aceitos pelo chat. Em escuta local, só localhost (barra DNS rebinding: um site de fora que aponte o
    próprio domínio para 127.0.0.1 teria Origin == Host e passaria numa checagem só de "mesma origem"). Em escuta pública
    sem ORIGENS_PERMITIDAS, None = qualquer Host (o domínio de produção não é conhecido)."""
    from urllib.parse import urlparse
    local = {f"localhost:{porta}", f"127.0.0.1:{porta}", f"[::1]:{porta}"}
    nomes = {urlparse(o).netloc for o in extras}
    if host_escuta in ("127.0.0.1", "localhost", "::1"):
        return local | nomes
    return (local | nomes) if nomes else None


def origem_permitida(origem, host, hosts_ok, extras=()):
    """O Origin do navegador tem de ser a própria página (Origin == Host) com um Host aceito, ou estar em `extras`."""
    from urllib.parse import urlparse
    o = urlparse(origem or "")
    if not o.netloc:
        return False
    if f"{o.scheme}://{o.netloc}" in extras:
        return True
    return o.netloc == (host or "") and (hosts_ok is None or o.netloc in hosts_ok)


def ip_cliente(cabecalhos, par, confiar_proxy):
    """IP para o limite do chat. Atrás de um proxy SEU (CONFIAR_PROXY=1) vem de CF-Connecting-IP ou do último item de
    X-Forwarded-For (o que o proxy viu; o resto o cliente forja). Sem proxy, só o endereço da conexão."""
    if confiar_proxy:
        if cabecalhos.get("CF-Connecting-IP"):
            return cabecalhos["CF-Connecting-IP"].strip()
        if cabecalhos.get("X-Forwarded-For"):
            return cabecalhos["X-Forwarded-For"].split(",")[-1].strip()
    return par


def criar_servidor(host, porta, uf, so_uf, so_br, intervalo):
    """Monta o servidor HTTP e o cache (sem iniciar nada). `servir` o inicia; os testes o usam numa porta efêmera."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlparse
    pagina = os.path.join(RAIZ_PROJETO, "frontend", "painel.html")
    global CACHE_TTL
    CACHE_TTL = intervalo
    cache = CacheVivo(intervalo)
    confiar_proxy = os.environ.get("CONFIAR_PROXY") == "1"          # atrás de Cloudflare/nginx: o IP real vem no cabeçalho
    extras = {o.strip() for o in os.environ.get("ORIGENS_PERMITIDAS", "").split(",") if o.strip()}
    srv_ref = {}

    def fn_api(sigla, turno):
        def calcular():
            dados = dados_2t(sigla) if turno == 2 else dados_web(sigla, so_uf, so_br)
            dados["servidor"] = dict(gerado=round(time.time(), 1), ultimo_ok=round(ESTAT["ultimo_ok"], 1), falhas=ESTAT["falhas"])
            return _json(dados)
        return calcular

    def gerar(sigla, turno):
        return cache.obter(("api", sigla, turno), fn_api(sigla, turno))

    def gerar_mapa(sigla, cargo, turno=1):
        return cache.obter(("mapa", sigla, cargo, turno), lambda: _json(mapa_municipios(sigla, cargo, turno)),
                           ttl=intervalo if SIM["ativo"] else max(intervalo, 60))     # 167 arquivos por vez: quase tudo 304

    # ---- chat (RAG + ferramentas): ver chat.py -----------------------------------------------------------------
    def dados_do_painel(sigla, turno):
        p = gerar(sigla.lower(), turno)
        if not p:
            raise RuntimeError("dados do TSE indisponíveis no momento")
        return json.loads(p.js)

    def mapa_do_painel(sigla, cargo, turno):
        p = gerar_mapa(sigla.lower(), cargo, turno)
        if not p:
            raise RuntimeError("dados por região indisponíveis no momento")
        return json.loads(p.js)

    chat = None
    try:
        from chat import Chat
        from chat_ferramentas import Ferramentas
        from rag import busca
        chat = Chat(Ferramentas(dados_do_painel, mapa_do_painel, busca.carregar()))
        if not chat.ativo:
            log.warning("o chat não vai responder. %s", chat.motivo_inativo())
    except Exception as e:                                         # noqa: BLE001 - sem trechos indexados ou sem dependências
        log.warning("Chat desativado: %s: %s  (rode 'python -m rag.ingestao' e 'pip install -r requirements.txt')",
                    type(e).__name__, e)

    geo_cache, html_cache = {}, {}
    json_tipo = "application/json; charset=utf-8"

    class H(BaseHTTPRequestHandler):
        timeout = 60                                               # conexão parada não prende thread para sempre

        def _html(self):
            m = os.path.getmtime(pagina)
            if html_cache.get("m") != m:
                with open(pagina, "rb") as f:
                    html_cache.update(m=m, p=empacotar(f.read()))
            return html_cache["p"]

        def _enviar(self, p, tipo, cache_ctl="no-store", status=200):
            if p.etag and status == 200 and self.headers.get("If-None-Match") == p.etag:
                self.send_response(304)
                self.send_header("ETag", p.etag)
                self.send_header("Cache-Control", cache_ctl)
                self.end_headers()
                return
            gz = p.gz is not None and "gzip" in (self.headers.get("Accept-Encoding") or "")
            corpo = p.gz if gz else p.js
            try:
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", cache_ctl)
                self.send_header("Vary", "Accept-Encoding")
                if gz:
                    self.send_header("Content-Encoding", "gzip")
                if p.etag:
                    self.send_header("ETag", p.etag)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", CSP)
                self.end_headers()
                self.wfile.write(corpo)
            except (ConnectionError, OSError):                     # navegador fechou/recarregou no meio da resposta
                pass

        def _pequeno(self, obj, status=200):
            self._enviar(empacotar(_json(obj), etag=False), json_tipo, status=status)

        # ---- POST /api/chat -> fluxo de eventos (SSE) ----
        def do_POST(self):
            if urlparse(self.path).path != "/api/chat" or chat is None:
                self.send_error(404)
                return
            hosts_ok = hosts_permitidos(host, srv_ref["porta"], extras)
            if (not origem_permitida(self.headers.get("Origin"), self.headers.get("Host"), hosts_ok, extras)
                    or not (self.headers.get("Content-Type") or "").startswith("application/json")):
                self.send_error(403)                               # nenhum site de fora gasta a chave da API
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 16384:                             # pergunta + texto da página (até ~4500 caracteres)
                    raise ValueError
                req = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, OSError):
                self.send_error(400)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                ip = ip_cliente(self.headers, self.client_address[0], confiar_proxy)
                for ev in chat.responder(req.get("conversa"), req.get("mensagem", ""), ip, contexto=req.get("contexto")):
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            except (ConnectionError, OSError):                     # o navegador fechou: o gerador é encerrado
                pass

        # ---- GET ----
        def do_GET(self):
            rota, qs = urlparse(self.path).path, parse_qs(urlparse(self.path).query)
            sel = qs.get("uf", [uf])[0].lower()
            sel = sel if sel in UFS else uf
            turno = 2 if qs.get("turno", ["1"])[0] == "2" else 1
            if rota in ("/", "/index.html"):
                self._enviar(self._html(), "text/html; charset=utf-8", "no-cache")
            elif rota == "/healthz":
                idade = cache.idade_fixos()
                ok = idade is None or idade < 120
                self._pequeno(dict(ok=ok, idade_dados_s=None if idade is None else round(idade, 1), falhas_tse=ESTAT["falhas"]),
                              200 if ok else 503)
            elif rota == "/api/chat/status":
                self._pequeno(chat.status() if chat else dict(ativo=False, motivo="Chat não configurado."))
            elif rota == "/geo/br" or (rota.startswith("/geo/uf/") and rota[8:].lower() in UFS):
                import geo
                if rota not in geo_cache:
                    geo_cache[rota] = empacotar(geo.geojson_br() if rota == "/geo/br" else geo.geojson_uf(rota[8:]))
                self._enviar(geo_cache[rota], "application/json", "public, max-age=86400")
            elif rota in ("/api", "/api/mapa"):
                if rota == "/api":
                    p = gerar(sel, turno)
                else:
                    cg = qs.get("cargo", ["3"])[0]
                    p = gerar_mapa(sel, int(cg) if cg in ("1", "3", "5") else 3, turno)
                if p:
                    self._enviar(p, json_tipo, "public, max-age=3, s-maxage=8")
                else:
                    self._pequeno({}, 503)
            elif rota == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.send_error(404)

        def log_message(self, fmt, *a):
            if len(a) > 1 and str(a[1]).startswith(("4", "5")):
                log.info("%s %s", self.address_string(), fmt % a)

    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 64

        def handle_error(self, request, client_address):          # sem traceback para conexões abortadas
            pass

    srv = Srv((host, porta), H)
    srv_ref["porta"] = srv.server_address[1]                       # porta 0 (testes) vira a porta sorteada
    return SimpleNamespace(srv=srv, cache=cache, gerar=gerar, gerar_mapa=gerar_mapa, fn_api=fn_api)


def servir(host, porta, uf, so_uf, so_br, intervalo, abrir_navegador=True):
    if not SIM["ativo"]:
        HIST.abrir(os.path.join(RAIZ_PROJETO, "logs", "historico_2t.json"))      # recarrega do disco, se houver
    s = criar_servidor(host, porta, uf, so_uf, so_br, intervalo)
    url = f"http://localhost:{porta}"
    log.info("Painel em %s  (escutando em %s:%s; Ctrl+C para encerrar)", url, host, porta)
    for k in dict.fromkeys(("rn", uf)):                            # o duelo de cada estado é renovado sempre, com ou sem público
        s.cache.registrar(("api", k, 2), s.fn_api(k, 2), fixo=True)
        threading.Thread(target=lambda k=k: [s.gerar(k, 2), s.gerar(k, 1)], daemon=True).start()
    threading.Thread(target=lambda: s.gerar_mapa(uf, 3, 2), daemon=True).start()
    if abrir_navegador:
        import webbrowser
        webbrowser.open(url)
    s.srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uf", default="rn")
    ap.add_argument("--so-uf", action="store_true")
    ap.add_argument("--so-br", action="store_true")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--web", action="store_true", help="sobe o servidor web")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="endereço de escuta (padrão 127.0.0.1; use 0.0.0.0 para a rede/produção)")
    ap.add_argument("--porta", type=int, default=int(os.environ.get("PORT", 8765)))
    ap.add_argument("--sem-navegador", action="store_true", help="não abre o navegador (automático fora do localhost)")
    ap.add_argument("--simular-2t", action="store_true",
                    help="TESTE: fabrica arquivos de 2º turno a partir do 1º, com apuração que avança até 100%%")
    ap.add_argument("--sim-inicio", default="18:55", help="hora (HH:MM) em que o relógio simulado começa; 17:00 mostra a espera inteira até as 19h")
    ap.add_argument("--sim-duracao", type=int, default=300, help="segundos reais para o relógio simulado ir de 17h a 22h (1 min simulado = duração/300 s)")
    ap.add_argument("--intervalo", type=int, default=None, help="segundos entre consultas (padrão: 60 no terminal, 15 no navegador, 2 na simulação)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    uf = a.uf.lower()
    if uf not in UFS:
        sys.exit(f"UF inválida: {a.uf}")
    if a.simular_2t:
        try:
            h, m = a.sim_inicio.split(":")
            inicio = int(h) * 60 + int(m)
        except ValueError:
            sys.exit(f"--sim-inicio inválido: {a.sim_inicio} (use HH:MM)")
        inicio = min(max(inicio, SIM_INICIO_MIN), SIM_FIM_MIN)
        # começar mais tarde = voltar o "t0": o relógio já nasce em `inicio`, sem a espera das horas puladas
        t0 = time.time() - (inicio - SIM_INICIO_MIN) * a.sim_duracao / (SIM_FIM_MIN - SIM_INICIO_MIN)
        SIM.update(ativo=True, t0=t0, duracao=float(a.sim_duracao))
        log.warning("*** SIMULAÇÃO DE 2º TURNO ATIVA (dados fabricados; relógio simulado 17h→22h em %ss) ***", a.sim_duracao)
    if a.web:
        local = a.host in ("127.0.0.1", "localhost", "::1")
        servir(a.host, a.porta, uf, a.so_uf, a.so_br, a.intervalo or (2 if a.simular_2t else 15),
               abrir_navegador=local and not a.sem_navegador and "PORT" not in os.environ)
        return
    while True:
        try:
            if not a.uma_vez:
                print("\033[2J\033[H", end="")
            renderizar(uf, a.so_uf, a.so_br)
        except Exception as e:                                       # não derruba o painel por uma falha de rede
            print(f"{R}Falha neste ciclo: {e}{Z}")
        if a.uma_vez:
            break
        for s in range(a.intervalo or 60, 0, -1):
            print(f"\r{D}próxima atualização em {s:2d}s (Ctrl+C para sair){Z} ", end="", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
