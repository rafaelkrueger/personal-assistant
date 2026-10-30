"""Roda o gravador (VadRecorder) e o detector do nome (WakeStream/Vosk) REAIS da Cassandra sobre as cenas da sala.

uso: python run_bench.py <nome> [--dist perto,2-3m,sala,longe] [--tv silencio,tv] [--neg 1] [--tvonly 0]
                         [--set modulo.CONST=valor ...] [--workers 4]
Grava results/<nome>.jsonl e imprime o resumo.
"""
import argparse
import json
import os
import sys
import time
import types
import zlib
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).parent
REPO = Path(os.environ.get("CASSANDRA_REPO") or Path(__file__).resolve().parents[2])  # cópia fora do repo: aponte
MODEL = HERE / "vosk-model-small-pt-0.3"


def _setup(settings):
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(HERE))
    fake = types.ModuleType("pyaudio")
    fake.paInt16 = 8
    fake.PyAudio = lambda: types.SimpleNamespace(terminate=lambda: None)
    sys.modules["pyaudio"] = fake
    from cassandra import audio_routes  # noqa: PLC0415

    audio_routes.mic_choice = lambda: "usb"
    audio_routes.bluetooth_mic_input = lambda: None
    import importlib  # noqa: PLC0415

    for spec in settings:
        target, value = spec.split("=", 1)
        mod, const = target.rsplit(".", 1)
        setattr(importlib.import_module(mod), const, json.loads(value))


_LOCAL = None


def _init(settings):
    global _LOCAL
    _setup(settings)
    from cassandra.local_speech import LocalSpeech  # noqa: PLC0415

    _LOCAL = LocalSpeech(["cassandra", "casandra", "cassanda", "kassandra", "kasandra", "cassandre", "cassandro",
                          "sandra", "alessandra", "lessandra"], model_path=str(MODEL))
    _LOCAL._load()


class EndOfScene(Exception):
    pass


class FakeStream:
    def __init__(self, audio):
        self.a = audio
        self.pos = 0  # amostras a 48 kHz já lidas

    def read(self, n, exception_on_overflow=False):
        if self.pos + n > len(self.a):
            raise EndOfScene
        chunk = self.a[self.pos:self.pos + n]
        self.pos += n
        return chunk.tobytes()

    def stop_stream(self):
        pass

    def close(self):
        pass


def run_scene(job):
    import wave  # noqa: PLC0415

    import sim  # noqa: PLC0415
    from cassandra import vad_recorder  # noqa: PLC0415

    clip_id, dist, tv, seed = job
    audio, marks = sim.scene(clip_id, dist, tv, seed)
    fake = FakeStream(audio)
    rec = vad_recorder.VadRecorder(energy_threshold=sim.ENERGY_FLOOR, silence_duration=0.6, max_duration=30.0)
    rec._stream = (fake, sim.RATE, 1440)
    rec._opened_choice = "usb"
    rec._source_checked = 1e18
    recs = []
    t0 = time.perf_counter()
    while True:
        ws = _LOCAL.stream()
        cand = {"pos": None, "instant": None, "decided": None}

        def on_frame(f, ws=ws, cand=cand):  # o mesmo que MicrophoneInputSource faz a cada quadro
            if ws.feed(f) and cand["pos"] is None:
                cand["pos"] = fake.pos / sim.RATE
            live = rec.live
            if live is not None:
                ok = ws.instant(live.quiet, live.onset)
                if ws.instant_info is not None and cand["decided"] is None:
                    cand["decided"] = fake.pos / sim.RATE  # quando a decisão do bip na hora saiu (sim ou não)
                if ok and cand["instant"] is None:
                    cand["instant"] = fake.pos / sim.RATE
            return ws.heard

        try:
            path = rec.record_utterance(silence_duration=0.4, on_frame=on_frame, min_voiced=None)
        except EndOfScene:
            heard, only, text = ws.close()
            if heard:  # achou o nome, mas a gravação não terminou até o fim da cena
                recs.append({"start": None, "end": None, "heard": True, "text": text, "cand": cand["pos"],
                             "unterminated": True, "instant": cand["instant"], "decided": cand["decided"],
                             "info": ws.instant_info})
            break
        heard, only, text = ws.close()
        end = fake.pos / sim.RATE
        if path:
            with wave.open(path, "rb") as w:
                dur = w.getnframes() / w.getframerate()
            os.unlink(path)
            recs.append({"start": round(end - dur, 3), "end": round(end, 3), "heard": heard, "text": text,
                         "cand": cand["pos"], "name_start": getattr(ws, "name_start", None),
                         "instant": cand["instant"], "decided": cand["decided"], "info": ws.instant_info,
                         "peak": round(rec.last_peak)})
        elif heard:
            recs.append({"start": None, "end": round(end, 3), "heard": heard, "text": text, "cand": cand["pos"],
                         "dropped": True, "instant": cand["instant"], "decided": cand["decided"],
                         "info": ws.instant_info})
    return {"clip": clip_id, "dist": dist, "tv": tv, "seed": seed, "marks": marks, "recs": recs,
            "cpu": round(time.perf_counter() - t0, 2), "len": round(len(audio) / sim.RATE, 2)}


def summarize(rows):
    from collections import defaultdict  # noqa: PLC0415

    out = defaultdict(lambda: {"pos": 0, "hit": 0, "neg": 0, "fa": 0, "cand_lat": [], "end_lat": [], "len": [],
                               "never_end": 0})
    for r in rows:
        m = r["marks"]
        k = (r["dist"], r["tv"])
        s = out[k]
        if m["label"] == "pos":
            s["pos"] += 1
            # a gravação que cobre o fim do nome e ouviu o nome
            def covers(x):
                if x["cand"] is not None:
                    return m["name_start"] - 0.1 <= x["cand"] <= m["name_end"] + 1.5
                return x.get("start") is not None and x["start"] <= m["name_end"] + 0.05 <= x["end"] + 0.15
            hit = [x for x in r["recs"] if x["heard"] and covers(x)]
            if hit:
                s["hit"] += 1
                x = hit[0]
                if x["cand"] is not None:
                    s["cand_lat"].append(x["cand"] - m["name_end"])
                if x.get("unterminated"):
                    s["never_end"] += 1
                else:
                    s["end_lat"].append(x["end"] - m["speech_end"])
                    s["len"].append(x["end"] - x["start"])
        elif m["label"] == "neg":
            s["neg"] += 1
            if any(x["heard"] and ((x["cand"] is not None and m["speech_start"] <= x["cand"] <= m["speech_end"] + 0.6)
                   or (x.get("start") is not None and x["end"] >= m["speech_start"]
                       and x["start"] <= m["speech_end"] + 0.3)) for x in r["recs"]):
                s["fa"] += 1
    import statistics as st  # noqa: PLC0415

    print(f"{'distância':8} {'fundo':9} {'acerto':>12} {'falso':>10} {'cand(s)':>8} {'fim(s)':>7} "
          f"{'p90fim':>7} {'grav(s)':>8} {'sem fim':>7}")
    for (d, tv), s in sorted(out.items(), key=lambda kv: (list(DIST_ORDER).index(kv[0][0]), kv[0][1])):
        med = lambda v: f"{st.median(v):.2f}" if v else "-"  # noqa: E731
        p90 = lambda v: f"{sorted(v)[int(len(v) * 0.9) - 1 if len(v) > 1 else 0]:.2f}" if v else "-"  # noqa: E731
        print(f"{d:8} {tv:9} {s['hit']:>4}/{s['pos']:<3} {100 * s['hit'] / max(1, s['pos']):3.0f}% "
              f"{s['fa']:>3}/{s['neg']:<3} {med(s['cand_lat']):>8} {med(s['end_lat']):>7} {p90(s['end_lat']):>7} "
              f"{med(s['len']):>8} {s['never_end']:>7}")


DIST_ORDER = ("perto", "2-3m", "sala", "longe")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--dist", default="2-3m,sala,longe")
    ap.add_argument("--tv", default="silencio,tv")
    ap.add_argument("--neg", type=float, default=1.0, help="fração das frases sem o nome")
    ap.add_argument("--speakers", type=int, default=18)
    ap.add_argument("--labels", default="pos,neg", help="pos, neg e/ou hard (palavras soltas parecidas com o nome)")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    import sim  # noqa: PLC0415

    jobs = []
    for c in sim.corpus():
        if c["label"] not in args.labels.split(","):
            continue
        spk = int(c["id"].split("_s")[1])
        if spk >= args.speakers:
            continue
        if c["label"] == "neg" and (zlib.crc32(c["id"].encode()) % 1000) / 1000 >= args.neg:
            continue
        for d in args.dist.split(","):
            for tv in args.tv.split(","):
                seed = zlib.crc32(f"{c['id']}|{d}|{tv}".encode())
                jobs.append((c["id"], d, tv, seed))
    t0 = time.time()
    with Pool(args.workers, initializer=_init, initargs=(args.set,)) as pool:
        rows = pool.map(run_scene, jobs, chunksize=4)
    (HERE / "results").mkdir(exist_ok=True)
    with open(HERE / "results" / f"{args.name}.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} cenas em {time.time() - t0:.0f} s  ({args.name}; {' '.join(args.set) or 'código atual'})")
    summarize(rows)


if __name__ == "__main__":
    main()
