#!/usr/bin/env python3
"""Acompanhamento minuto a minuto da apuração 2026 (TSE) no terminal.

Mostra, para o estado escolhido (padrão RN) e para o Brasil: presidente, governador, senador, deputado federal
e (no estado) deputado estadual, dizendo quem está eleito/se elegendo e se vai haver 2º turno.

Uso:
    python acompanhar.py                 # RN + Brasil, atualiza a cada 60 s
    python acompanhar.py --uf SP         # outro estado
    python acompanhar.py --so-uf         # só o estado
    python acompanhar.py --so-br         # só o Brasil
    python acompanhar.py --uma-vez       # imprime uma vez e sai
    python acompanhar.py --intervalo 30

Só usa a biblioteca padrão do Python. Fonte: https://resultados.tse.jus.br/oficial (divulgação oficial).
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

BASE = "https://resultados.tse.jus.br/oficial"
RAIZ = BASE + "/ele2026"
DATA_2T = "2026-10-25"
ELE_PRES, ELE_DEMAIS = "6257", "6259"          # presidente | governador, senador e deputados
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb", "pe", "pi", "pr",
       "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]
BRT = timezone(timedelta(hours=-3))

os.system("")                                   # liga sequências ANSI no console do Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
V, R, A, C, D, N, Z = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[2m", "\033[1m", "\033[0m"


# ---- coleta -----------------------------------------------------------------------------------------------
def baixar(url):
    if SIM["ativo"]:                                   # --simular-2t: o 2º turno é fabricado a partir do 1º
        fab = simulado(url)
        if fab is not False:
            return fab
    return _baixar_http(url)


def _baixar_http(url):
    for tentativa in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 eleicoes-2026-painel"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 429):
                return None
        except Exception:
            pass
        time.sleep(1 + tentativa)
    return None


def url_u(ele, uf, cargo):
    return f"{RAIZ}/{ele}/dados/{uf}/{uf}-c{cargo:04d}-e{int(ele):06d}-u.json"


CACHE_URL, CACHE_TTL = {}, 0          # no modo navegador, trocar de estado reaproveita o que já foi baixado


def baixar_cache(url):
    t, j = CACHE_URL.get(url, (0, None))
    if CACHE_TTL and j is not None and time.time() - t < CACHE_TTL:
        return j
    j = baixar(url)
    if j is not None:
        CACHE_URL[url] = (time.time(), j)
    return j


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
                                    t2=c.get("e") == "s" and "turno" in c.get("st", "").lower(), valido=c.get("dvt", "").startswith("V"),
                                    agr=ag.get("com", ag.get("nm", ""))))
    return sorted(out, key=lambda c: -c["votos"])


def apurado(j):
    return num(j["s"]["pstn"] if "pstn" in j["s"] else j["s"]["pst"])


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
        if turno == 2 and modo == "2t" and j2:
            r = resumo_mapa(j2, 2)
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
SIM = dict(ativo=False, t0=0.0, duracao=600.0)
_COD = dict(t=0.0, v=None)


def codigos_turno():
    """Códigos de eleição do 1º e do 2º turno (campo `cdt2` do ele-c.json). Se falhar, usa os já anunciados."""
    if _COD["v"] and time.time() - _COD["t"] < 600:
        return _COD["v"]
    v = dict(pres1=ELE_PRES, pres2="6258", dem1=ELE_DEMAIS, dem2="6260")
    try:
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
    except Exception:
        pass
    _COD.update(t=time.time(), v=v)
    return v


def t2_disponivel():
    """O TSE já publicou os arquivos do 2º turno? (antes de 25/10 eles dão 404)"""
    c = codigos_turno()
    return baixar_cache(url_u(c["pres2"], "br", 1)) is not None


def meta():
    return dict(t2_disponivel=t2_disponivel(), simulado=SIM["ativo"], data_2t=DATA_2T)


def simulado(url):
    """Modo --simular-2t: devolve um arquivo de 2º turno fabricado a partir do equivalente do 1º (False = não é 2º turno)."""
    c = codigos_turno()
    for k1, k2 in (("pres1", "pres2"), ("dem1", "dem2")):
        e1, e2 = c[k1], c[k2]
        if f"/{e2}/" in url and f"e{int(e2):06d}" in url:
            u1 = url.replace(f"/{e2}/", f"/{e1}/").replace(f"e{int(e2):06d}", f"e{int(e1):06d}")
            j1 = _baixar_http(u1)
            return sintetizar_2t(j1, url) if j1 else None
    return False


def sintetizar_2t(j1, url):
    """Só para testar: os dois finalistas ficam com os votos do 1º turno + uma divisão pseudo-aleatória (estável por
    arquivo) dos votos dos demais, e a apuração avança com o tempo até 100% em SIM['duracao'] segundos."""
    import copy
    import hashlib
    import random
    rnd = random.Random(int(hashlib.md5(url.encode()).hexdigest(), 16) % 2 ** 32)
    cs = [c for c in candidatos(j1) if c["valido"]]
    fin = ([c for c in cs if c["t2"]] or cs[:2])[:2]
    if len(fin) < 2:
        return None
    prog = min(1.0, (time.time() - SIM["t0"]) / SIM["duracao"])
    local = min(1.0, max(0.0, prog * 1.25 - 0.25 * rnd.random()))
    outros = sum(c["votos"] for c in cs if c["n"] not in {f["n"] for f in fin})
    lean = 0.5 + (rnd.random() - 0.5) * 0.3
    novos = {fin[0]["n"]: round((fin[0]["votos"] + lean * outros) * local),
             fin[1]["n"]: round((fin[1]["votos"] + (1 - lean) * outros) * local)}
    total = sum(novos.values())
    fmt = lambda x: f"{x:.2f}".replace(".", ",")
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
                    c.update(vap=str(v), pvap=fmt(p), pvapn=f"{p:.9f}".replace(".", ","))
                    venceu = local >= 1 and v == max(novos.values())
                    c.update(e="s" if venceu else "n", st=("Eleito" if venceu else "Não eleito") if local >= 1 else "")
                if pa["cand"]:
                    pars.append(pa)
            if pars:
                ag["par"] = pars
                agrs.append(ag)
        cg["agr"] = agrs
    ts = int(num(j["s"]["ts"]))
    j["s"].update(st=str(round(ts * local)), pst=fmt(local * 100), pstn=f"{local * 100:.9f}".replace(".", ","))
    j["v"].update(vv=str(total), vvc=str(total))
    j["t"] = "2"
    agora = datetime.now(BRT)
    j["dg"], j["hg"], j["ht"] = agora.strftime("%d/%m/%Y"), agora.strftime("%H:%M:%S"), agora.strftime("%H:%M:%S")
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
    """No 2º turno vence quem tiver mais votos válidos (maioria absoluta, já que são só dois)."""
    if len(cs) < 2 or apurado(j) <= 0:
        return dict(tipo="aberto", rotulo="AGUARDANDO APURAÇÃO", texto="Os primeiros resultados ainda não chegaram.")
    a, b = cs[0], cs[1]
    dif, r = a["votos"] - b["votos"], restantes(j)
    pp = a["pct"] - b["pct"]
    if a["eleito"]:
        return dict(tipo="eleito", rotulo="ELEITO", texto=f"{a['nome']} (confirmado pelo TSE)")
    if dif > r:
        return dict(tipo="1turno", rotulo="VITÓRIA DEFINIDA (projeção)",
                    texto=f"{a['nome']} lidera por {milhar(dif)} votos e o que falta apurar não alcança essa diferença")
    cor = "2turno" if dif < 0.25 * r else "aberto"
    return dict(tipo=cor, rotulo="DISPUTA ABERTA",
                texto=f"{a['nome']} lidera por {milhar(dif)} votos ({pct(pp)} p.p.); faltam cerca de {milhar(r)} votos válidos")


def web_2t(j2, j1):
    """Cartão do duelo. Ao vivo (j2) mostra o 2º turno; antes dele, os finalistas com o desempenho do 1º turno (j1)."""
    if not j1:
        return None
    fin = finalistas_1t(j1)
    nums = {c["n"] for c in fin}
    ref = {c["n"]: c["pct"] for c in fin}
    refv = {c["n"]: c["votos"] for c in fin}
    base = base_1t(j1, nums)
    campos = ("nome", "n", "sg", "votos", "pct", "eleito")
    if j2:
        cs = [c for c in candidatos(j2) if c["valido"]][:2]
        return dict(ao_vivo=True, apur=apurado(j2), ht=j2.get("ht", ""), situacao=situacao_2t(j2, cs), base=base,
                    cands=[dict({k: c[k] for k in campos}, pct1t=ref.get(c["n"], 0), votos1t=refv.get(c["n"], 0)) for c in cs])
    return dict(ao_vivo=False, apur=0, ht=j1.get("ht", ""), base=base,
                situacao=dict(tipo="aberto", rotulo="AGUARDANDO O 2º TURNO", texto=f"A votação é em {DATA_2T[8:]}/{DATA_2T[5:7]}."),
                cands=[dict({k: c[k] for k in campos}, pct1t=c["pct"], votos1t=c["votos"]) for c in fin])


def dados_2t(uf):
    c = codigos_turno()
    ok = t2_disponivel()
    d1 = coletar([(c["pres1"], "br", 1)] + [(c["pres1"], u, 1) for u in UFS] + [(c["dem1"], uf, 3)])
    d2 = coletar([(c["pres2"], "br", 1)] + [(c["pres2"], u, 1) for u in UFS] + [(c["dem2"], uf, 3)]) if ok else {}
    out = dict(turno=2, meta=meta(), agora=datetime.now(BRT).strftime("%H:%M:%S"),
               pres=web_2t(d2.get(("br", 1)), d1.get(("br", 1))))
    fin_gov = finalistas_1t(d1[(uf, 3)]) if d1.get((uf, 3)) else []
    out["uf"] = dict(sigla=uf.upper(), em_2turno=bool(d1.get((uf, 3)) and any(x["t2"] for x in fin_gov)),
                     gov=web_2t(d2.get((uf, 3)), d1.get((uf, 3))))
    mapa = {}
    nums = {x["n"] for x in finalistas_1t(d1[("br", 1)])} if d1.get(("br", 1)) else set()
    for u in UFS:
        j2, j1 = d2.get((u, 1)), d1.get((u, 1))
        r = resumo_mapa(j2, 2) if j2 else resumo_duelo(j1, nums)
        if r:
            mapa[u.upper()] = {"1": r}
    out["mapa_br"] = mapa
    return out


def servir(porta, uf, so_uf, so_br, intervalo):
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    pagina = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "painel.html")
    global CACHE_TTL
    CACHE_TTL = intervalo
    cache = {}                                                     # uf -> (instante, json)
    lock = threading.Lock()

    def gerar(sigla=uf, turno=1):
        with lock:
            t, js = cache.get((sigla, turno), (0.0, b"{}"))
            if time.time() - t > intervalo:                        # várias abas não multiplicam as consultas ao TSE
                try:
                    dados = dados_2t(sigla) if turno == 2 else dados_web(sigla, so_uf, so_br)
                    js = json.dumps(dados, ensure_ascii=False).encode("utf-8")
                    cache[(sigla, turno)] = (time.time(), js)
                except Exception as e:
                    print(f"Falha neste ciclo: {e}")
            return js

    cache_mapa, lock_mapa = {}, threading.Lock()                  # lock próprio: o mapa de MG não trava o /api

    def gerar_mapa(sigla, cargo, turno=1):
        with lock_mapa:
            t, js = cache_mapa.get((sigla, cargo, turno), (0.0, b"{}"))
            if time.time() - t > max(intervalo, 30):
                try:
                    js = json.dumps(mapa_municipios(sigla, cargo, turno), ensure_ascii=False).encode("utf-8")
                    cache_mapa[(sigla, cargo, turno)] = (time.time(), js)
                except Exception as e:
                    print(f"Falha no mapa {sigla}/{cargo}: {e}")
            return js

    # ---- chat (RAG + ferramentas): ver chat.py -----------------------------------------------------------------
    def dados_do_painel(sigla, turno):
        js = json.loads(gerar(sigla.lower(), turno))
        if not js:
            raise RuntimeError("dados do TSE indisponíveis no momento")
        return js

    def mapa_do_painel(sigla, cargo, turno):
        js = json.loads(gerar_mapa(sigla.lower(), cargo, turno))
        if not js:
            raise RuntimeError("dados por região indisponíveis no momento")
        return js

    chat = None
    try:
        from chat import Chat
        from chat_ferramentas import Ferramentas
        from rag import busca
        chat = Chat(Ferramentas(dados_do_painel, mapa_do_painel, busca.carregar()))
        if not chat.ativo:
            print(f"AVISO: o chat não vai responder. {chat.motivo_inativo()}")
    except Exception as e:                                         # sem trechos indexados ou sem dependências
        print(f"Chat desativado: {type(e).__name__}: {e}  (rode 'python -m rag.ingestao' e 'pip install -r requirements.txt')")
    origens = {f"http://localhost:{porta}", f"http://127.0.0.1:{porta}"}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            """POST /api/chat -> fluxo de eventos (SSE). Só JSON e só da própria página, para nenhum site de fora
            conseguir gastar a chave da API do usuário."""
            from urllib.parse import urlparse
            if urlparse(self.path).path != "/api/chat" or chat is None:
                self.send_error(404)
                return
            origem = self.headers.get("Origin")
            if (origem and origem not in origens) or not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self.send_error(403)
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 4096:
                    raise ValueError
                req = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                for ev in chat.responder(req.get("conversa"), req.get("mensagem", ""), self.client_address[0]):
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            except (ConnectionError, OSError):                     # o navegador fechou: o gerador é encerrado
                pass

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            rota, qs = urlparse(self.path).path, parse_qs(urlparse(self.path).query)
            sel = qs.get("uf", [uf])[0].lower()
            if rota == "/api/chat/status":
                corpo = json.dumps(chat.status() if chat else dict(ativo=False, motivo="Chat não configurado."),
                                   ensure_ascii=False).encode("utf-8")
                tipo = "application/json; charset=utf-8"
            elif rota == "/geo/br":
                import geo
                corpo, tipo = geo.geojson_br(), "application/json"
            elif rota.startswith("/geo/uf/") and rota[8:].lower() in UFS:
                import geo
                corpo, tipo = geo.geojson_uf(rota[8:]), "application/json"
            elif rota == "/api/mapa":
                cg = qs.get("cargo", ["3"])[0]
                corpo = gerar_mapa(sel if sel in UFS else uf, int(cg) if cg in ("1", "3", "5") else 3,
                                   2 if qs.get("turno", ["1"])[0] == "2" else 1)
                tipo = "application/json; charset=utf-8"
            elif rota.startswith("/api"):
                corpo = gerar(sel if sel in UFS else uf, 2 if qs.get("turno", ["1"])[0] == "2" else 1)
                tipo = "application/json; charset=utf-8"
            else:
                with open(pagina, "rb") as f:
                    corpo, tipo = f.read(), "text/html; charset=utf-8"
            try:
                self.send_response(200)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corpo)
            except (ConnectionError, OSError):                     # navegador fechou/recarregou no meio da resposta
                pass

        def log_message(self, *a):
            pass

    class Srv(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):          # sem traceback para conexões abortadas
            pass

    srv = Srv(("127.0.0.1", porta), H)
    url = f"http://localhost:{porta}"
    print(f"Painel no navegador: {url}   (Ctrl+C para encerrar)")
    threading.Thread(target=gerar, daemon=True).start()            # aquece o cache antes da primeira aba pedir
    webbrowser.open(url)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uf", default="rn")
    ap.add_argument("--so-uf", action="store_true")
    ap.add_argument("--so-br", action="store_true")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--web", action="store_true", help="abre o painel no navegador (localhost)")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--simular-2t", action="store_true",
                    help="TESTE: fabrica arquivos de 2º turno a partir do 1º, com apuração que avança até 100%%")
    ap.add_argument("--sim-duracao", type=int, default=600, help="segundos até a apuração simulada chegar a 100%%")
    ap.add_argument("--intervalo", type=int, default=None, help="segundos entre consultas (padrão: 60 no terminal, 15 no navegador)")
    a = ap.parse_args()
    uf = a.uf.lower()
    if uf not in UFS:
        sys.exit(f"UF inválida: {a.uf}")
    if a.simular_2t:
        SIM.update(ativo=True, t0=time.time(), duracao=float(a.sim_duracao))
        print(f"*** SIMULAÇÃO DE 2º TURNO ATIVA (dados fabricados; 100% em {a.sim_duracao}s) ***")
    if a.web:
        servir(a.porta, uf, a.so_uf, a.so_br, a.intervalo or 15)
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
