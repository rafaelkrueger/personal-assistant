"""Números no formato brasileiro escritos por extenso antes de virar voz.

A voz (OpenAI/Azure/Piper) lê "R$ 7.000,00" como "sete reais" — o ponto de milhar vira vírgula decimal. Aqui
valores em reais e números com ponto de milhar / vírgula decimal viram palavras: "sete mil reais".
"""
from __future__ import annotations

import re

_UNITS = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
          "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_TENS = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_HUNDREDS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
             "oitocentos", "novecentos"]
_SCALES = [("", ""), ("mil", "mil"), ("milhão", "milhões"), ("bilhão", "bilhões"), ("trilhão", "trilhões")]


def _below_1000(n: int) -> str:
    if n == 100:
        return "cem"
    parts = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_HUNDREDS[h])
    if rest:
        if rest < 20:
            parts.append(_UNITS[rest])
        else:
            t, u = divmod(rest, 10)
            parts.append(_TENS[t] + (f" e {_UNITS[u]}" if u else ""))
    return " e ".join(parts)


def number_words(n: int) -> str:
    """1234567 -> 'um milhão duzentos e trinta e quatro mil quinhentos e sessenta e sete'."""
    if n < 0:
        return "menos " + number_words(-n)
    if n == 0:
        return "zero"
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        sing, plur = _SCALES[i]
        if i == 1 and g == 1:
            chunk = "mil"
        elif i == 0:
            chunk = _below_1000(g)
        else:
            chunk = f"{_below_1000(g)} {sing if g == 1 else plur}"
        words.append(chunk)
    # "e" antes do último grupo quando ele é < 100 ou uma centena redonda: "mil e quinhentos", "dois mil e dez"
    if len(words) > 1 and groups[0] and (groups[0] < 100 or groups[0] % 100 == 0):
        return " ".join(words[:-1]) + " e " + words[-1]
    return " ".join(words)


def _int(s: str) -> int:
    return int(s.replace(".", ""))


def _reais(sign: str, whole: str, cents: str | None) -> str:
    n = _int(whole)
    c = int((cents or "0").ljust(2, "0")[:2])
    big = n >= 1_000_000 and n % 1_000_000 == 0 and not c          # "dois milhões de reais"
    parts = []
    if n or not c:
        parts.append(f"{number_words(n)} {'real' if n == 1 else ('de reais' if big else 'reais')}")
    if c:
        parts.append(f"{number_words(c)} {'centavo' if c == 1 else 'centavos'}")
    return ("menos " if sign else "") + " e ".join(parts)


# R$ 7.000,00 | R$7000 | -R$ 1.234,5 | R$ -50,00
_MONEY = re.compile(r"(-\s?)?R\$\s?(-\s?)?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?(?!\d)")
# 12.345,67 | 1.000 (ponto de milhar) — só quando o padrão é inequívoco (grupos de 3 dígitos)
_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+)(?:,(\d+))?(?![\d.,]*\d)")
# 12,5 (vírgula decimal)
_DECIMAL = re.compile(r"(?<![\d.,])(\d+),(\d+)(?![\d.,]*\d)")


def _decimal_words(whole: int, frac: str | None) -> str:
    out = number_words(whole)
    if frac:
        out += " vírgula " + (number_words(int(frac)) if not frac.startswith("0") else " ".join(_UNITS[int(d)] for d in frac))
    return out


def for_speech(text: str) -> str:
    """Troca valores em reais e números no formato brasileiro por palavras (o resto do texto fica igual)."""
    if not text or not any(ch.isdigit() for ch in text):
        return text
    text = _MONEY.sub(lambda m: _reais(m.group(1) or m.group(2), m.group(3), m.group(4)), text)
    text = _THOUSANDS.sub(lambda m: _decimal_words(_int(m.group(1)), m.group(2)), text)
    text = _DECIMAL.sub(lambda m: _decimal_words(int(m.group(1)), m.group(2)), text)
    return text
