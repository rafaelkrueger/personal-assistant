"""Resumo do bip na hora (WakeStream.instant) de rodadas já feitas pelo run_bench.

uso: python instant.py <rodada> [--conf 0.9] [--secs 0.3,1.3]
Rode a bancada com o filtro aberto (--set cassandra.local_speech.INSTANT_MIN_CONF=0
--set cassandra.local_speech.INSTANT_NAME_SECONDS=[0,9]) e escolha a confiança e a duração aqui, sem rodar de novo.
"""
import argparse
import json
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def group(text: str) -> str:
    t = re.sub(r"[^a-zà-ú ]", "", text.lower()).split()
    if t == ["cassandra"]:
        return "só o nome"
    if t and t[0] in {"ô", "ei", "oi"}:
        return "ô/ei + nome"
    if t and t[0] == "cassandra":
        return "nome + pedido"
    return "nome no fim"


def passes(info: dict | None, conf: float, secs: tuple[float, float], partial: bool = False,
           speech: float = 99.0) -> bool:
    """A decisão bipa com esses limites? partial = só o texto parcial (sem fechar o resultado: sem confiança);
    speech = máximo de fala (s) do começo até a pausa."""
    if not info or info.get("speech", 0.0) > speech:
        return False
    if partial:
        return info.get("heard") == "cassandra"
    if info.get("conf") is None:
        return False
    if info.get("why") and not info["why"].startswith(("confiança", "duração")):
        return False
    return info["conf"] >= conf and secs[0] <= info["seconds"] <= secs[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--conf", type=float, default=0.9)
    ap.add_argument("--secs", default="0.3,1.3")
    ap.add_argument("--partial", action="store_true", help="só o texto parcial decide (sem confiança/duração)")
    ap.add_argument("--speech", type=float, default=99.0, help="máximo de fala (s) do começo até a pausa")
    args = ap.parse_args()
    secs = tuple(float(v) for v in args.secs.split(","))
    rows = [json.loads(line) for run in args.runs for line in open(HERE / "results" / f"{run}.jsonl", encoding="utf-8")]

    pos = defaultdict(lambda: {"n": 0, "hit": 0, "inst": 0, "lat": [], "why": Counter()})
    false_inst = defaultdict(lambda: [0, 0])  # (dist, tv, rótulo) -> [cenas, bips falsos]
    fired = Counter()
    confs = {"pos": [], "neg": []}
    for r in rows:
        m = r["marks"]
        if m["label"] == "pos":
            k = (r["dist"], r["tv"], group(m["text"]))
            s = pos[k]
            s["n"] += 1
            hit = [x for x in r["recs"] if x["heard"] and x.get("cand") is not None
                   and m["name_start"] - 0.1 <= x["cand"] <= m["name_end"] + 1.5]
            if not hit:
                continue
            s["hit"] += 1
            x = hit[0]
            info = x.get("info")
            if info and info.get("conf") is not None and not (info.get("why") or "").startswith("não era"):
                confs["pos"].append(info["conf"])
            if x.get("decided") is not None and passes(info, args.conf, secs, args.partial, args.speech):
                s["inst"] += 1
                s["lat"].append(x["decided"] - m["name_end"])
            else:
                why = (info or {}).get("why") or ("sem decisão" if not info else "filtro")
                if passes(info, 0, (0, 9)):
                    why = "confiança/duração"
                s["why"][re.sub(r"[\d.]+", "#", why)[:40]] += 1
        else:
            k = (r["dist"], r["tv"], m["label"])
            false_inst[k][0] += 1
            for x in r["recs"]:
                info = x.get("info")
                if info and info.get("conf") is not None and not (info.get("why") or "").startswith("não era"):
                    confs["neg"].append(info["conf"])
                if x.get("decided") is not None and passes(info, args.conf, secs, args.partial, args.speech):
                    false_inst[k][1] += 1
                    fired[m["text"]] += 1
                    break

    print(("filtro: só o texto parcial" if args.partial else f"filtro: confiança >= {args.conf}, duração {secs[0]}-{secs[1]} s")
          + (f", fala até a pausa <= {args.speech} s" if args.speech < 99 else ""))
    print(f"{'distância':8} {'fundo':9} {'frase':14} {'ouviu':>9} {'na hora':>12} {'atraso(s)':>9} {'p90':>5}  por que não")
    for (d, tv, g), s in sorted(pos.items()):
        lat = s["lat"]
        med = f"{st.median(lat):.2f}" if lat else "-"
        p90 = f"{sorted(lat)[int(len(lat) * 0.9) - 1 if len(lat) > 1 else 0]:.2f}" if lat else "-"
        why = ", ".join(f"{w} {n}" for w, n in s["why"].most_common(3))
        print(f"{d:8} {tv:9} {g:14} {s['hit']:>4}/{s['n']:<4} {s['inst']:>4} {100 * s['inst'] / max(1, s['hit']):3.0f}%"
              f"   {med:>7} {p90:>5}  {why}")
    print()
    for (d, tv, lab), (n, f) in sorted(false_inst.items()):
        print(f"{d:8} {tv:9} {lab:5} bips falsos: {f}/{n}")
    if fired:
        print("frases que bipariam:", dict(fired.most_common(12)))
    for lab, v in confs.items():
        if v:
            v = sorted(v)
            q = [v[int(len(v) * p)] for p in (0.05, 0.1, 0.25, 0.5)]
            print(f"confiança do nome sozinho ({lab}, n={len(v)}): p5 {q[0]:.2f} p10 {q[1]:.2f} p25 {q[2]:.2f} "
                  f"mediana {q[3]:.2f}")


if __name__ == "__main__":
    main()
