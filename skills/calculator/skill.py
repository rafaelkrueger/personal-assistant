"""Calculator skill: safe math and unit conversions."""
from __future__ import annotations

import ast
import operator
import re

from skills.base import Skill

_TRIGGER = ["quanto é", "quanto e", "calcul", "converte", "converter", "quanto são", "quanto sao"]

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
}

_LENGTH = {
    "km": 1000, "m": 1, "cm": 0.01, "mm": 0.001,
    "mi": 1609.34, "milha": 1609.34, "milhas": 1609.34,
    "ft": 0.3048, "pe": 0.3048, "pes": 0.3048,
    "pol": 0.0254, "inch": 0.0254, "inches": 0.0254,
}
_WEIGHT = {
    "kg": 1, "g": 0.001, "mg": 0.000001, "t": 1000,
    "lb": 0.453592, "oz": 0.0283495,
}
_VOLUME = {
    "l": 1, "litro": 1, "litros": 1,
    "ml": 0.001, "mililitro": 0.001, "mililitros": 0.001,
    "galao": 3.78541, "xicara": 0.236588, "colher": 0.015,
}
_UNIT_GROUPS = [_LENGTH, _WEIGHT, _VOLUME]


class CalculatorSkill(Skill):
    name = "calculator"

    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in _TRIGGER)

    def handle(self, text: str) -> str:
        t = text.lower()

        temp = self._try_temperature(t)
        if temp:
            return temp

        conv = self._try_conversion(t)
        if conv:
            return conv

        result = self._try_math(text)
        if result:
            return result

        return "Nao consegui calcular. Tente: 'quanto e 15% de 200' ou 'converte 5 km em metros'."

    def _try_temperature(self, text: str) -> str | None:
        m = re.search(
            r"(-?\d+(?:[.,]\d+)?)\s*(?:graus?\s*)?(celsius|fahrenheit|kelvin|°c|°f|°k)\s+"
            r"(?:em|para)\s+(celsius|fahrenheit|kelvin|°c|°f|°k)",
            text,
        )
        if not m:
            return None
        val = float(m.group(1).replace(",", "."))
        norm = {"celsius": "c", "fahrenheit": "f", "kelvin": "k", "°c": "c", "°f": "f", "°k": "k"}
        src = norm.get(m.group(2), m.group(2))
        dst = norm.get(m.group(3), m.group(3))
        kelvin = val + 273.15 if src == "c" else (val - 32) * 5 / 9 + 273.15 if src == "f" else val
        result = kelvin - 273.15 if dst == "c" else (kelvin - 273.15) * 9 / 5 + 32 if dst == "f" else kelvin
        return f"{val} {src.upper()} = {self._fmt(result)} {dst.upper()}"

    def _try_conversion(self, text: str) -> str | None:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s+(\w+)\s+(?:em|para)\s+(\w+)", text)
        if not m:
            return None
        val = float(m.group(1).replace(",", "."))
        src, dst = m.group(2), m.group(3)
        for group in _UNIT_GROUPS:
            if src in group and dst in group:
                result = val * group[src] / group[dst]
                return f"{val} {src} = {self._fmt(result)} {dst}"
        return None

    def _try_math(self, text: str) -> str | None:
        text2 = re.sub(r"(\d+(?:\.\d+)?)\s*%\s+de\s+(\d+(?:\.\d+)?)", r"(\1/100)*\2", text)
        m = re.search(r"[\d\s\+\-\*\/\(\)\.\%\^]+", text2)
        if not m:
            return None
        expr = m.group(0).strip().replace("^", "**")
        if not re.search(r"\d", expr):
            return None
        result = self._safe_eval(expr)
        if result is None:
            return None
        return f"Resultado: {self._fmt(result)}"

    @staticmethod
    def _safe_eval(expr: str):
        try:
            tree = ast.parse(expr.strip(), mode="eval")
            return CalculatorSkill._eval_node(tree.body)
        except Exception:
            return None

    @staticmethod
    def _eval_node(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            left = CalculatorSkill._eval_node(node.left)
            right = CalculatorSkill._eval_node(node.right)
            if left is None or right is None:
                return None
            op = _OPS.get(type(node.op))
            return op(left, right) if op else None
        if isinstance(node, ast.UnaryOp):
            operand = CalculatorSkill._eval_node(node.operand)
            op = _OPS.get(type(node.op))
            return op(operand) if op and operand is not None else None
        return None

    @staticmethod
    def _fmt(n: float) -> str:
        if n == int(n):
            return str(int(n))
        return f"{n:.4f}".rstrip("0").rstrip(".")
