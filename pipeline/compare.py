"""Translate one fixed batch with several engines and save the outputs anonymised for a blind review.

Usage: python -I -X utf8 compare.py <size> <model>:<think> ...
Writes D:\\cp77-ro\\bench\\blind.json ({"lines": [{id, en, en_m, g, versions: {A: {f, m}, B: ...}}]})
and D:\\cp77-ro\\bench\\key.json (letter -> engine, seconds) — the judge must not read key.json.
"""
import json
import pathlib
import random
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import translate as T  # noqa: E402

OUT = pathlib.Path(r"D:\cp77-ro\bench")
size = int(sys.argv[1])
con = sqlite3.connect(T.DB, timeout=60)
gloss = T.Glossary(con)
batch = [u for b in T.build_batches(con, 400, {"p2"}) for u in b if u["domain"] == "dialogue"][200:200 + size]
system, user, _ = T.batch_prompt(batch, gloss)
specs = sys.argv[2:]
letters = list("ABCD")[:len(specs)]
random.shuffle(letters)
key, outs = {}, {}
for spec, letter in zip(specs, letters):
    model, think = spec.rsplit(":", 1)
    think = {"false": False, "true": True}.get(think, think)
    t0 = time.time()
    res = llm.chat_json(system, user, think=think, model=model, retries=3, timeout=1200)
    key[letter] = {"engine": spec, "seconds": round(time.time() - t0, 1)}
    outs[letter] = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
    print(spec, key[letter]["seconds"], "s", flush=True)
OUT.mkdir(exist_ok=True)
lines = []
for i, u in enumerate(batch):
    lines.append({"id": i, "file": u["file"].split("\\en-us\\")[-1], "en": u["en_f"], "en_m": u["en_m"],
                  "v_gendered": u["g"],
                  "versions": {L: {"f": (outs[L].get(i) or {}).get("f", ""), "m": (outs[L].get(i) or {}).get("m", "")}
                               for L in sorted(outs)}})
(OUT / "blind.json").write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
print("saved", len(lines), "lines")
