"""Reprodução da noite REAL do 2º turno de 2022 (Lula x Bolsonaro) no painel, com a ordem real em que os boletins de urna chegaram.
Só para ensaio (`painel_server.py --web --replay-2022`): os candidatos são rebatizados com os de 2026 (Lula e Flávio no presidente;
no governador do RN, o mesmo 2º turno de presidente nos 167 municípios vira Cadu x Allyson). Precisa dos dados baixados por
`python modelo/dados_2022.py` e `python modelo/dados_2022_municipios.py` (modelo/cache/).  Só biblioteca padrão."""
import gzip
import json
import os
from bisect import bisect_right
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "..", "modelo", "cache")
SECOES = os.path.join(CACHE, "2022_2t_secoes.jsonl.gz")
MUNIC = os.path.join(CACHE, "2022_municipios.json")
ZERO = datetime(2022, 10, 30)


def disponivel():
    return os.path.exists(SECOES) and os.path.exists(MUNIC)


class _Serie:
    """Acumulado de uma unidade (estado ou município) por minuto de chegada dos boletins."""

    def __init__(self):
        self.linhas = []                  # (minuto, aptos, comp, a, b)
        self.pronto = None

    def add(self, m, aptos, comp, a, b):
        self.linhas.append((m, aptos, comp, a, b))

    def fecha(self):
        self.linhas.sort()
        self.tempos = [x[0] for x in self.linhas]
        ac = [0, 0, 0, 0]
        self.cum = []
        for _, aptos, comp, a, b in self.linhas:
            ac = [ac[0] + aptos, ac[1] + comp, ac[2] + a, ac[3] + b]
            self.cum.append(tuple(ac))
        self.total = self.cum[-1] if self.cum else (0, 0, 0, 0)
        self.n = len(self.linhas)

    def em(self, m):
        """dict(aptos, comp, a, b, secoes) apurados até o minuto m, e totais da unidade."""
        i = bisect_right(self.tempos, m)
        c = self.cum[i - 1] if i else (0, 0, 0, 0)
        return dict(apt_c=c[0], comp_c=c[1], a=c[2], b=c[3], secoes_c=i, apt_t=self.total[0], a_t=self.total[2], b_t=self.total[3], secoes_t=self.n)


class Replay2022:
    def __init__(self):
        self.uf, self.mun = {}, {}
        with gzip.open(SECOES, "rt", encoding="utf-8") as f:
            for linha in f:
                s = json.loads(linha)
                m = int((datetime.strptime(s["t"], "%Y-%m-%dT%H:%M:%S") - ZERO).total_seconds() // 60)
                self.uf.setdefault(s["uf"].lower(), _Serie()).add(m, s["aptos"], s["comp"], s["a"], s["b"])
                self.mun.setdefault((s["uf"].lower(), s["mun"]), _Serie()).add(m, s["aptos"], s["comp"], s["a"], s["b"])
        for sr in list(self.uf.values()) + list(self.mun.values()):
            sr.fecha()
        with open(MUNIC, encoding="utf-8") as f:
            self.t1 = json.load(f)["1"]          # 1º turno de 2022: {uf: {municipio: {numero: votos}}}

    # ---- 2º turno -----------------------------------------------------------------------------------------------------------
    def estado(self, uf, m):
        return self.uf[uf].em(m) if uf in self.uf else None

    def municipio(self, uf, mun, m):
        sr = self.mun.get((uf, mun))
        return sr.em(m) if sr else None

    def brasil(self, m):
        """Soma dos estados (sem o exterior), como no painel."""
        tot = dict(apt_c=0, comp_c=0, a=0, b=0, secoes_c=0, apt_t=0, a_t=0, b_t=0, secoes_t=0)
        for uf, sr in self.uf.items():
            if uf == "zz":
                continue
            for k, v in sr.em(m).items():
                tot[k] += v
        return tot

    # ---- 1º turno (prior) -------------------------------------------------------------------------------------------------------
    def votos_1t(self, uf=None, mun=None):
        """{numero_do_votavel: votos} do 1º turno de 2022 para o município, o estado ou o país."""
        out = {}
        ufs = [uf.upper()] if uf and uf != "br" else list(self.t1)
        for u in ufs:
            if u == "ZZ" and not uf:
                continue
            for cod, votos in self.t1.get(u, {}).items():
                if mun and cod != mun:
                    continue
                for n, v in votos.items():
                    out[n] = out.get(n, 0) + v
        return out
