"""Só a TV ligada (sem ninguém chamar): candidatos a nome por minuto (cada um vira uma conferência na nuvem) e bips
na hora (WakeStream.instant) — esses tocam o bip antes da nuvem, então têm que ser ~0.

uso: python tvonly.py <nome> [--set modulo.CONST=valor ...]
"""
import os
import sys
from multiprocessing import Pool

import numpy as np

import run_bench
import sim


def job(args):
    level, seed = args
    rng = np.random.default_rng(seed)
    total = 90 * sim.RATE
    nz = sim.noise()
    tr = sim.tv_track()
    bg = np.tile(nz, total // len(nz) + 2)[rng.integers(0, len(nz)):][:total].copy()
    off = rng.integers(0, len(tr))
    bg += np.tile(tr, total // len(tr) + 2)[off:off + total] * sim.TV_LEVELS[level]
    audio = np.clip(bg, -32768, 32767).astype(np.int16)
    from cassandra import vad_recorder  # noqa: PLC0415

    fake = run_bench.FakeStream(audio)
    rec = vad_recorder.VadRecorder(energy_threshold=400, silence_duration=0.6, max_duration=30.0)
    rec._stream = (fake, sim.RATE, 1440)
    rec._opened_choice = "usb"
    rec._source_checked = 1e18
    cands, texts, infos = 0, [], []
    while True:
        ws = run_bench._LOCAL.stream()

        def on_frame(f, ws=ws):
            ws.feed(f)
            if rec.live is not None:
                ws.instant(rec.live.quiet, rec.live.speech_before)
            return ws.heard

        try:
            path = rec.record_utterance(silence_duration=0.4, on_frame=on_frame, min_voiced=None)
        except run_bench.EndOfScene:
            h, _, t = ws.close()
            cands += h
            break
        h, _, t = ws.close()
        if path:
            os.unlink(path)
        if h:
            cands += 1
            texts.append(t)
            infos.append(ws.instant_info)
    return level, cands, texts, infos


if __name__ == "__main__":
    settings = [a.split("=", 1)[1] if a.startswith("--set=") else a for a in sys.argv[2:] if a != "--set"]
    jobs = [(lv, s) for lv in ("tv", "tv_alta") for s in range(8)]
    with Pool(4, initializer=run_bench._init, initargs=(settings,)) as pool:
        out = pool.map(job, jobs)
    for lv in ("tv", "tv_alta"):
        c = sum(x[1] for x in out if x[0] == lv)
        inst = [i for x in out if x[0] == lv for i in x[3] if i and i.get("conf") is not None]
        print(f"{sys.argv[1]} {lv}: {c} candidatos em {8 * 1.5:.0f} min de TV = {c / 12:.2f}/min; "
              f"decisões do bip na hora com o nome sozinho: {[(i['conf'], i['seconds'], i['why']) for i in inst]}")
    print("exemplos:", [t for x in out for t in x[2]][:8])
