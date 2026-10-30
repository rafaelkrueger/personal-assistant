import json, sys
sys.path.insert(0, ".")
import run_bench
for name in sys.argv[1:]:
    rows = [json.loads(l) for l in open(f"results/{name}.jsonl", encoding="utf-8")]
    print(f"== {name}: {len(rows)} cenas")
    run_bench.summarize(rows)
