"""Translate the few strings still showing English (QA failures + never translated) with a Claude model.

Same prompt, masking, glossary/term base/phrasebook and QA as translate.py; one retry with the QA notes.
Usage: python -I -X utf8 fix_leftovers.py [--model claude-sonnet-5-5]
"""
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import translate as T  # noqa: E402

args = sys.argv[1:]
MODEL = "anthropic:" + (args[args.index("--model") + 1] if "--model" in args else "claude-sonnet-5-5")

con = sqlite3.connect(T.DB, timeout=60)
con.execute("DELETE FROM translations WHERE qa_status = 'fail'")
con.commit()
gloss = T.Glossary(con)
T.tbase(con)
batches = T.build_batches(con, 20, None)
units = [u for b in batches for u in b]
print(f"{len(units)} units in {len(batches)} batches", flush=True)


def run(batch, notes=None):
    system, user, terms = T.batch_prompt(batch, gloss, notes)
    res = llm.chat_json(system, user, think="medium", model=MODEL, retries=3, timeout=900, schema=llm.LINES_SCHEMA)
    got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
    ok, bad = [], {}
    for i, u in enumerate(batch):
        r = got.get(i) or {}
        f, lf, nf = T.qa(u["en_f"], T.unmask(r.get("f") or "", T.mask(u["en_f"])[1]), gloss.banned)
        m_raw = T.unmask(r.get("m") or "", T.mask(u["en_m"] or u["en_f"])[1])
        m, lm, nm = T.qa(u["en_m"] or u["en_f"], m_raw, gloss.banned) if m_raw else ("", "ok", [])
        if T.tbase().exact(u["en_f"]):
            f, lf, nf = T.tbase().exact(u["en_f"]), "ok", []
        if "fail" in (lf, lm):
            bad[i] = "; ".join(nf + nm)
        else:
            ok.append((u, f, "" if m == f else m, "warn" if "warn" in (lf, lm) else "ok", "; ".join(nf + nm), terms))
    return ok, bad


done = []
for b in batches:
    ok, bad = run(b)
    done += ok
    if bad:  # one retry with the QA notes
        sub = [b[i] for i in sorted(bad)]
        ok2, bad2 = run(sub, {j: bad[i] for j, i in enumerate(sorted(bad))})
        done += ok2
        for i in bad2:
            print("still failing:", sub[i]["en_f"][:90], "|", bad2[i], flush=True)
now = time.time()
for u, f, m, lvl, notes, terms in done:
    for sid in u["write_ids"]:
        con.execute("""INSERT OR REPLACE INTO translations (string_id, ro_female, ro_male, model, batch_secs, qa_status,
                       qa_notes, created_at, glossary_terms, prompt_version, polished)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                    (sid, f, m, MODEL, 0, lvl, notes, now, ",".join(terms), T.PROMPT_VERSION))
con.commit()
print(f"saved {len(done)}/{len(units)} units; cost ${llm.cost(MODEL.split(':', 1)[1]):.3f}")
