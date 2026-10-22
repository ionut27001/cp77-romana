"""Benchmark engine settings on one fixed batch of untranslated quest dialogue (nothing is saved).

Usage: python -I -X utf8 bench.py <size> <model>:<think> [<model>:<think> ...]
  think: false | true | low | medium | high
"""
import json
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import translate as T  # noqa: E402

size = int(sys.argv[1])
con = sqlite3.connect(T.DB, timeout=60)
gloss = T.Glossary(con)
batches = T.build_batches(con, 400, {"p2"})
batch = [u for b in batches for u in b if u["domain"] == "dialogue"][:size]
system, user, terms = T.batch_prompt(batch, gloss)
print(f"{len(batch)} lines, prompt {len(system) + len(user)} chars, {len(terms)} glossary terms\n")
for spec in sys.argv[2:]:
    model, think = spec.rsplit(":", 1) if spec.count(":") > 1 else (spec, "medium")
    think = {"false": False, "true": True}.get(think, think)
    t0 = time.time()
    try:
        res = llm.chat_json(system, user, think=think, model=model, retries=2, timeout=900)
    except Exception as e:
        print(f"== {spec}: ERROR {e}\n")
        continue
    secs = time.time() - t0
    out = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
    fails = sum(1 for i, u in enumerate(batch) if T.qa(u["en_f"], (out.get(i) or {}).get("f", ""), gloss.banned)[1] == "fail")
    print(f"== {spec}: {secs:.1f}s  -> {len(batch) / secs * 60:.0f} lines/min per request; "
          f"answered {len(out)}/{len(batch)}, QA fail {fails}")
    for i in range(0, len(batch), max(1, len(batch) // 8)):
        r = out.get(i) or {}
        print(f"   EN: {batch[i]['en_f'][:95]}\n   RO: {r.get('f', '—')[:95]}" + (f"\n   ♂ : {r['m'][:95]}" if r.get("m") else ""))
    print()
