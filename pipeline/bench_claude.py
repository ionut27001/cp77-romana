"""Blind test of Claude as editor/translator on the polish sample (nothing is saved to the translations).

Versions: current text, Haiku 5.5 polish, Sonnet 5.5 polish, Haiku 5.5 fresh translation.
Writes D:\\cp77-ro\\bench\\blind.json + key.json (letters shuffled) and prints exact cost per version.
Usage: python -I -X utf8 bench_claude.py [lines]
"""
import json
import pathlib
import random
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import polish as P  # noqa: E402
import translate as T  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
con = sqlite3.connect(T.DB, timeout=60)
gloss = T.Glossary(con)
T.tbase(con)
us = P.units(con)
random.seed(7)
start = random.randrange(0, len(us) - N)
us = us[start:start + N]
for u in us:
    u.setdefault("ctx", "")
batches = P.batches_of(us, 40)


def run_polish(model, effort):
    P.FULL = True
    out = {}
    for b in batches:
        system, user = P.prompt(b, gloss)
        res = llm.chat_json(system, user, think=effort, model=model, retries=3, timeout=900)
        got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
        for i, u in enumerate(b):
            fm = P.check(u, got[i], gloss) if i in got else None
            out[id(u)] = fm or (u["ro_f"], u["ro_m"])
    return out


def run_translate(model, effort):
    out = {}
    for b in batches:
        system, user, _ = T.batch_prompt(b, gloss)
        res = llm.chat_json(system, user, think=effort, model=model, retries=3, timeout=900)
        got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
        for i, u in enumerate(b):
            r = got.get(i) or {}
            f, lvl, _ = T.qa(u["en_f"], T.unmask(r.get("f") or "", T.mask(u["en_f"])[1]), gloss.banned)
            m = T.unmask(r.get("m") or "", T.mask(u["en_m"] or u["en_f"])[1])
            out[id(u)] = (f if lvl != "fail" else u["ro_f"], m if m != f else "")
    return out


variants = {"current": {id(u): (u["ro_f"], u["ro_m"]) for u in us}}
costs = {}
for name, fn, model in (("haiku-polish", run_polish, "anthropic:claude-haiku-5-5"),
                        ("sonnet-polish", run_polish, "anthropic:claude-sonnet-5-5"),
                        ("haiku-translate", run_translate, "anthropic:claude-haiku-5-5")):
    before = llm.cost(model.split(":", 1)[1])
    variants[name] = fn(model, "medium")
    costs[name] = llm.cost(model.split(":", 1)[1]) - before
    changed = sum(1 for u in us if variants[name][id(u)] != (u["ro_f"], u["ro_m"]))
    print(f"{name}: changed {changed}/{len(us)} lines, ${costs[name]:.4f} "
          f"(${costs[name] / len(us) * 1000:.3f} per 1000 lines)", flush=True)

letters = list("ABCD")
random.Random(23).shuffle(letters)
key = dict(zip(letters, variants))
lines = []
for n, u in enumerate(us):
    lines.append({"id": n, "file": u["file"].split("\\en-us\\")[-1], "en": u["en_f"], "en_m": u["en_m"],
                  "v_gendered": u["g"],
                  "versions": {L: {"f": variants[v][id(u)][0], "m": variants[v][id(u)][1]} for L, v in key.items()}})
out = pathlib.Path(r"D:\cp77-ro\bench")
(out / "blind.json").write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
(out / "key.json").write_text(json.dumps({"key": key, "cost": costs, "usage": llm.usage}, indent=1), encoding="utf-8")
print("saved; usage:", llm.usage)
