"""Pedido falado -> dados: números, horários e durações por extenso, e o item de "adicionar leite na lista".

A transcrição devolve o que a pessoa falou, do jeito que falou: "sete e meia", "7h30", "às duas da tarde", "meia hora",
"um minuto e meio", "vinte e cinco minutos". Antes só valiam algarismos ("7", "6:30"): "seis e meia" virava "não
entendi o horário", "7h30" virava 7:00, "uma hora e meia" virava 1 hora e "me lembra às oito" virava timer de 8
minutos. E "Adicionar leite na lista" entrava na lista como "ar leite" (o verbo era cortado pelo radical).
"""
from __future__ import annotations

import re
import unicodedata

_UNITS = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
          "sete": 7, "oito": 8, "nove": 9}
_TEENS = {"dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
          "dezesseis": 16, "dezasseis": 16, "dezessete": 17, "dezassete": 17, "dezoito": 18, "dezenove": 19,
          "dezanove": 19}
_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70, "oitenta": 80,
         "noventa": 90}
_HUNDREDS = {"cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200, "trezentos": 300, "trezentas": 300}
_WORDS = {**_UNITS, **_TEENS, **_TENS, **_HUNDREDS}


def norm(text: str) -> str:
    """Minúsculas, sem acento, sem pontuação (menos ":"), "meio-dia" -> "meio dia"."""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9: ]+", " ", t.replace("-", " "))
    return " ".join(t.split())


def _class(value: int) -> int:
    return 3 if value >= 100 else 2 if value >= 20 else 1


def numbers(text: str) -> str:
    """Números por extenso viram algarismos ("vinte e cinco" -> "25", "cento e vinte" -> "120"). Texto já normalizado
    (norm). Só junta partes ligadas por "e" e cada vez menores, como se fala ("vinte e cinco", não "cinco e vinte")."""
    toks, out, i = text.split(), [], 0
    while i < len(toks):
        if toks[i] not in _WORDS:
            out.append(toks[i])
            i += 1
            continue
        total, last, j = _WORDS[toks[i]], _class(_WORDS[toks[i]]), i + 1
        while j + 1 < len(toks) and toks[j] == "e" and toks[j + 1] in _WORDS and _class(_WORDS[toks[j + 1]]) < last:
            total += _WORDS[toks[j + 1]]
            last = _class(_WORDS[toks[j + 1]])
            j += 2
        out.append(str(total))
        i = j
    return " ".join(out)


def duration_seconds(text: str) -> int | None:
    """"5 minutos", "meia hora", "uma hora e meia", "um minuto e meio", "1h30", "2 minutos e 30 segundos", "vinte e
    cinco minutos" -> segundos. Sem unidade nenhuma, um número sozinho vale minutos ("timer de 5"). None = sem
    duração."""
    t = numbers(norm(text))
    total, found = 0, False
    for m in re.finditer(r"\b(\d+)h(\d{2})\b", t):  # 1h30
        total += int(m.group(1)) * 3600 + int(m.group(2)) * 60
        found = True
    t = re.sub(r"\b\d+h\d{2}\b", " ", t)
    units = r"(horas?|hrs?|h|minutos?|mins?|segundos?|segs?|s)"
    for m in re.finditer(rf"\b(\d+)\s*{units}\b(?:\s+e\s+(meia|meio)\b)?", t):
        unit = m.group(2)
        mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
        total += int(m.group(1)) * mult + (mult // 2 if m.group(3) else 0)
        found = True
    # "1 hora e 30" (os minutos sem a palavra minutos)
    for m in re.finditer(r"\b\d+\s*(?:horas?|h)\s+e\s+(\d+)\b(?!\s*(?:minutos?|mins?|segundos?|segs?|s)\b)", t):
        total += int(m.group(1)) * 60
    if re.search(r"\bmeia\s+hora\b", t):
        total += 1800
        found = True
    if re.search(r"\bmeio\s+minuto\b", t):
        total += 30
        found = True
    if found:
        return total or None
    m = re.search(r"\b(\d+)\b", t)
    return int(m.group(1)) * 60 if m else None


def _period(t: str, hour: int) -> int:
    """"da tarde/da noite/à noite" somam 12; "12 da noite/da madrugada" = 0 ("boa noite" não é período)."""
    if re.search(r"\b(?:da|de|a) (?:tarde|noite)\b", t) and hour < 12:
        return hour + 12
    if re.search(r"\b(?:da|de|a) (?:noite|madrugada)\b", t) and hour == 12:
        return 0
    return hour


def _minutes(word: str | None) -> int:
    if not word:
        return 0
    return 30 if word == "meia" else int(word)


def time_of_day(text: str) -> str | None:
    """Horário falado -> "HH:MM": "às 7", "7h30", "19:45", "sete e meia", "pras seis e quinze", "duas da tarde",
    "dez para as oito" (7:50), "meio-dia", "meia-noite". Número de data ("dia 15") não é horário. None = sem horário."""
    t = numbers(norm(text))
    hour = minute = None
    if m := re.search(r"\bmeio dia(?: e (meia|\d{1,2}))?\b", t):
        return f"12:{_minutes(m.group(1)):02d}"
    if m := re.search(r"\bmeia noite(?: e (meia|\d{1,2}))?\b", t):
        return f"00:{_minutes(m.group(1)):02d}"
    if m := re.search(r"\b(\d{1,2})\s*(?::|h)\s*(\d{2})\b", t):
        hour, minute = int(m.group(1)), int(m.group(2))
    elif m := re.search(r"\b(\d{1,2})\s*(?:minutos?\s+)?(?:para|pras|pra)\s+(?:as\s+|a\s+)?(\d{1,2})\b", t):
        before, at = int(m.group(1)), int(m.group(2))
        if 0 < before < 60 and 0 <= at <= 24:  # "dez para as oito" = 7:50
            hour, minute = (at - 1) % 24, 60 - before
    if hour is None:
        after = r"(?:\s*(?:horas?|h))?(?:\s+e\s+(meia|\d{1,2})(?:\s*minutos?)?)?"
        for pattern in (rf"\b(?:as|a|pras|pra|para as|para a|ate as)\s+(\d{{1,2}}){after}",
                        rf"\b(\d{{1,2}})\s*(?:horas?|h)\b(?:\s+e\s+(meia|\d{{1,2}})(?:\s*minutos?)?)?",
                        r"(?<!dia )\b(\d{1,2})\s+e\s+(meia|\d{1,2})\b"):
            if m := re.search(pattern, t):
                hour, minute = int(m.group(1)), _minutes(m.group(2))
                break
    if hour is None:
        m = re.search(r"(?<!dia )(?<!dias )\b(\d{1,2})\b(?!\s*(?:minutos?|segundos?|dias?|de (?:janeiro|fevereiro|marco|"
                      r"abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)))", t)
        if not m:
            return None
        hour, minute = int(m.group(1)), 0
    hour = _period(t, hour)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


_LIST_PHRASE = re.compile(
    r"\b(?:n[ao]s?|a|as|à|às|para (?:a|as)|pra|para|da|das)?\s*(?:minha\s+|nossa\s+)?lista"
    r"(?:\s+(?:de|do|da)\s+(?:compras?|mercado|supermercado|feira|tarefas?|afazeres|coisas para fazer))?\b",
    re.IGNORECASE)
_POLITE = re.compile(r"\b(?:por favor|pra mim|para mim|a[ií]|tamb[eé]m)\b", re.IGNORECASE)
_ARTICLE = re.compile(r"^(?:o|a|os|as)\s+", re.IGNORECASE)


def item_after_verb(text: str, verbs: str, split: bool = False) -> list[str]:
    """O que vem depois do verbo (palavra inteira: "Adicionar leite" -> "leite", nunca "ar leite"), sem "na lista de
    compras", "por favor" nem o artigo do começo. split=True separa "leite, pão e ovos" em três itens."""
    m = re.search(rf"\b(?:{verbs})\b", text, re.IGNORECASE)
    if not m:
        return []
    payload = _LIST_PHRASE.sub(" ", text[m.end():])
    payload = _POLITE.sub(" ", payload)
    parts = re.split(r"\s*[,;]\s*|\s+e\s+", payload) if split else [payload]
    items = []
    for part in parts:
        part = _ARTICLE.sub("", " ".join(part.split()).strip(" .,:;!?-"))
        if part:
            items.append(part)
    return items


def first_action(text: str, actions: dict[str, str]) -> str | None:
    """Qual ação vem primeiro na frase (o verbo mais à esquerda): "tira o leite que eu coloquei" é tirar, "adiciona
    terminar o relatório" é adicionar."""
    best: tuple[int, str] | None = None
    for name, verbs in actions.items():
        m = re.search(rf"\b(?:{verbs})\b", text, re.IGNORECASE)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None


ADD_VERBS = (r"adicion\w*|acrescent\w*|coloc\w*|coloqu\w*|inclu\w*|inser\w*|insir\w*|anot\w*|bot[aeo]\w*|"
             r"p[oõ]e|ponha|ponho|pôr")  # "por" sozinho não: é o de "por favor"
REMOVE_VERBS = r"remov\w*|tira|tire|tirar|tiro|exclu\w*|apag\w*|risc\w*|delet\w*|elimin\w*"
DONE_VERBS = r"conclu\w*|marc\w*|finaliz\w*|termin\w*|complet\w*|fiz|feito|feita"
