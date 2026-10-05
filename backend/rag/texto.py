"""Limpeza e normalização de texto para a RAG (sem dependências externas, para ser fácil de testar)."""
import re
import unicodedata

# Títulos com letras espaçadas: "P R O G R A M A  D E  G O V E R N O" -> "PROGRAMA DE GOVERNO"
_ESPACADO = re.compile(r"(?<![\w])(?:[^\W\d_]\s){3,}[^\W\d_](?![\w])")
_LIDER = re.compile(r"\.{4,}|(?:\.\s){4,}|…{2,}")                  # pontilhado de índice
_HIFEN_QUEBRA = re.compile(r"(\w)-\s*\n\s*(\w)")
_ESPACOS = re.compile(r"[ \t\u00a0\u2009\u202f]+")


def juntar_letras_espacadas(txt):
    """Junta palavras escritas com uma letra por vez. Dois ou mais espaços separam palavras ("P R  D E" -> "PR DE")."""
    def troca(m):
        s = m.group(0)
        partes = re.split(r"\s{2,}", s)
        return " ".join(re.sub(r"\s", "", p) for p in partes)
    return _ESPACADO.sub(troca, txt)


def limpar_texto(txt):
    t = txt.replace("\u00ad", "")                                   # hífen opcional
    t = t.replace("\u0335", "r")                                   # a fonte do PDF do Allyson codifica o "r" assim (confirmado)
    t = _HIFEN_QUEBRA.sub(r"\1\2", t)
    t = juntar_letras_espacadas(t)
    t = t.replace("\r", "")
    t = _ESPACOS.sub(" ", t)
    t = re.sub(r"\s*\n\s*", " ", t)
    return t.strip()


def e_indice(txt):
    """Linha de sumário: pontilhado ou quase só números/pontos."""
    if _LIDER.search(txt):
        return True
    letras = sum(c.isalpha() for c in txt)
    return len(txt) > 12 and letras < 0.35 * len(txt)


def e_numero_de_pagina(txt):
    return bool(re.fullmatch(r"\s*(?:p[áa]g(?:ina)?\.?\s*)?\d{1,3}(?:\s*/\s*\d{1,3})?\s*", txt, re.I))


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


STOP = set("""a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre entre ate ao aos
e ou mas que se como mais menos muito muita muitos muitas ja nao sim ser sao foi sera estao esta estar ter tem tera
seu sua seus suas este esta estes estas esse essa esses essas isso isto aquele aquela quando onde qual quais quem
cada todo toda todos todas outro outra outros outras mesmo mesma tambem so apenas ainda pelo pela pelos pelas
vai vao ha foram sendo sera serao pode podem deve devem""".split())


def _stem(p):
    """Radicalização mínima para português: plurais, -mente e -ção/-ções. Só precisa ser coerente entre texto e consulta."""
    if len(p) <= 3:
        return p
    for suf, novo in (("coes", "cao"), ("oes", "ao"), ("aes", "ao"), ("ais", "al"), ("eis", "el"), ("ois", "ol"),
                      ("mente", "")):
        minimo = 2 if suf in ("coes", "oes", "aes") else 3          # "ações" -> "ação" (resto de 2 letras)
        if p.endswith(suf) and len(p) - len(suf) >= minimo:
            return p[: -len(suf)] + novo
    if p.endswith("s") and not p.endswith("ss"):
        p = p[:-1]
    return p


def tokens(txt):
    """Minúsculas, sem acento, sem palavras vazias, radicalizado."""
    base = sem_acento(txt).lower()
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", base) if w not in STOP and len(w) > 1]
