"""Second blind round: older Claude models as editors on the same 120 lines as bench_claude.py.

Reuses the Haiku 5.5 / Sonnet 5.5 outputs of the first round (bench\\blind.json + key.json, copied to
bench\\round1_*), adds Sonnet 5, Sonnet 4.6, Haiku 4.5, and writes a new blind file with 5 shuffled versions.
"""
import json
import pathlib
import random
import shutil
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import polish as P  # noqa: E402
import translate as T  # noqa: E402

B = pathlib.Path(r"D:\cp77-ro\bench")
if not (B / "round1_blind.json").exists():
    shutil.copy(B / "blind.json", B / "round1_blind.json")
    shutil.copy(B / "key.json", B / "round1_key.json")
r1 = json.loads((B / "round1_blind.json").read_text(encoding="utf-8"))["lines"]
k1 = {v: L for L, v in json.loads((B / "round1_key.json").read_text(encoding="utf-8"))["key"].items()}

con = sqlite3.connect(T.DB, timeout=60)
gloss = T.Glossary(con)
T.tbase(con)
us = P.units(con)
random.seed(7)
start = random.randrange(0, len(us) - 120)
us = us[start:start + 120]
assert [u["en_f"] for u in us] == [l["en"] for l in r1], "sample differs from round 1"
batches = P.batches_of(us, 40)
P.FULL = True

variants = {name: {n: (l["versions"][k1[name]]["f"], l["versions"][k1[name]]["m"]) for n, l in enumerate(r1)}
            for name in ("haiku-5.5-polish", "sonnet-5.5-polish") if False} or {}
variants["haiku-5.5-polish"] = {n: (l["versions"][k1["haiku-polish"]]["f"], l["versions"][k1["haiku-polish"]]["m"]) for n, l in enumerate(r1)}
variants["sonnet-5.5-polish"] = {n: (l["versions"][k1["sonnet-polish"]]["f"], l["versions"][k1["sonnet-polish"]]["m"]) for n, l in enumerate(r1)}

costs = {}
for name, model in (("sonnet-5-polish", "claude-sonnet-5"), ("sonnet-4.6-polish", "claude-sonnet-4-6"),
                    ("haiku-4.5-polish", "claude-haiku-4-5")):
    out = {}
    idx = 0
    for b in batches:
        system, user = P.prompt(b, gloss)
        try:
            res = llm.chat_json(system, user, think="medium", model="anthropic:" + model, retries=3, timeout=900,
                                  schema=llm.LINES_SCHEMA)
        except RuntimeError as e:
            print(name, "failed:", e)
            res = {"t": []}
        got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
        for i, u in enumerate(b):
            fm = P.check(u, got[i], gloss) if i in got else None
            out[idx] = fm or (u["ro_f"], u["ro_m"])
            idx += 1
    variants[name] = out
    costs[name] = llm.cost(model)
    changed = sum(1 for n, u in enumerate(us) if out[n] != (u["ro_f"], u["ro_m"]))
    print(f"{name}: changed {changed}/120, ${costs[name]:.4f} (${costs[name] / 120 * 1000:.3f} per 1000 lines)", flush=True)

letters = list("ABCDE")
random.Random(41).shuffle(letters)
key = dict(zip(letters, variants))
lines = [{"id": n, "file": l["file"], "en": l["en"], "en_m": l["en_m"], "v_gendered": l["v_gendered"],
          "versions": {L: {"f": variants[v][n][0], "m": variants[v][n][1]} for L, v in key.items()}}
         for n, l in enumerate(r1)]
(B / "blind.json").write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
(B / "key.json").write_text(json.dumps({"key": key, "cost": costs, "usage": llm.usage}, indent=1), encoding="utf-8")
print("saved")
