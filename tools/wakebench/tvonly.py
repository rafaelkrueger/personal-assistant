"""Só a TV ligada (sem ninguém chamar): quantos candidatos a nome por minuto (cada um vira uma conferência na nuvem)."""
import json, sys, time
from multiprocessing import Pool
import numpy as np
import run_bench, sim

def job(args):
    level, seed = args
    rng = np.random.default_rng(seed)
    total = 90 * sim.RATE
    nz = sim.noise(); tr = sim.tv_track()
    bg = np.tile(nz, total // len(nz) + 2)[rng.integers(0, len(nz)):][:total].copy()
    off = rng.integers(0, len(tr))
    bg += np.tile(tr, total // len(tr) + 2)[off:off + total] * sim.TV_LEVELS[level]
    audio = np.clip(bg, -32768, 32767).astype(np.int16)
    from cassandra import vad_recorder
    fake = run_bench.FakeStream(audio)
    rec = vad_recorder.VadRecorder(energy_threshold=400, silence_duration=0.6, max_duration=30.0)
    rec._stream = (fake, sim.RATE, 1440); rec._opened_choice = "usb"; rec._source_checked = 1e18
    cands, texts = 0, []
    import os
    while True:
        ws = run_bench._LOCAL.stream()
        try:
            path = rec.record_utterance(silence_duration=0.4, on_frame=lambda f, ws=ws: ws.feed(f) or ws.heard, min_voiced=None)
        except run_bench.EndOfScene:
            h, _, t = ws.close(); cands += h; break
        h, _, t = ws.close()
        if path: os.unlink(path)
        if h: cands += 1; texts.append(t)
    return level, cands, texts

if __name__ == "__main__":
    settings = sys.argv[2:]
    jobs = [(lv, s) for lv in ("tv", "tv_alta") for s in range(8)]
    with Pool(4, initializer=run_bench._init, initargs=(settings,)) as pool:
        out = pool.map(job, jobs)
    for lv in ("tv", "tv_alta"):
        c = sum(x[1] for x in out if x[0] == lv)
        print(f"{sys.argv[1]} {lv}: {c} candidatos em {8*1.5:.0f} min de TV = {c/12:.2f}/min")
    print("exemplos:", [t for x in out for t in x[2]][:8])
