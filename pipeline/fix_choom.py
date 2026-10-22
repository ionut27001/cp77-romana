"""Rewrite lines that inflect choom/choomba the Romanian way (choomul, choomii, choom-ul...) to the English forms.

The user's call (2026-10-22): if choom stays English, its forms stay English too: choom, chooms, choomba, choombas.
A Claude model edits only around the word; a line is saved only if no inflected form is left and its tags and
placeholders are intact. Old text goes to polish_backup. Lines with a review correction get the correction
fixed too (and the snapshot moved along, so pack.py keeps applying it).
Usage: python -I -X utf8 fix_choom.py [--model claude-haiku-5-5] [--dry-run]
"""
import json
import pathlib
import re
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import translate as T  # noqa: E402

args = sys.argv[1:]
MODEL = "anthropic:" + (args[args.index("--model") + 1] if "--model" in args else "claude-haiku-5-5")
DRY = "--dry-run" in args
INFLECTED = re.compile(r"\bchoom(?:b?a)?-?(?:ul|ii|i|ilor|ule|e|ului|lui)\b", re.I)

SYSTEM = """You fix a Romanian game translation (Cyberpunk 2077). The slang word "choom" (friend, buddy) and
"choomba" stay in English, and the user decided their FORMS stay English too:
  singular: choom / choomba      plural: chooms / choombas
NEVER Romanian endings: no choomul, choom-ul, choomii, choomi, choomilor, choomule, choome, choomului, choombi.
Rephrase only the words around it so the Romanian stays natural and grammatical, for example:
  "Choomul meu e la clinică" -> "Un choom de-al meu e la clinică"
  "Choomii mei" -> "Chooms de-ai mei" / "Chooms-ii" is WRONG
  "Ce faci, choomule?" -> "Ce faci, choom?"
  "Hai, choomilor!" -> "Hai, chooms!"
  "Choomul voia să ia datele cuiva" -> "Un choom voia să ia datele cuiva" (or "Tipul" if it refers back to someone)
  "mașina choomului" -> "mașina lui choom" / "mașina choom-ului" is WRONG
Keep the same word: choom stays choom(s), choomba stays choomba(s), never swap them. Both are masculine:
"chooms de-ai mei", never "de-ale mele". Keep the meaning: if a definite "the choom" points at someone specific,
use "ăla"/"tipul" rather than turning it into "un choom".
Change NOTHING else: same wording, same punctuation, same tags like <r1>/<i2>, {placeholders}, literal \\n.
Each input line has id, "f" (main text) and optionally "m" (male-V variant). Return every id with "f" and "m"
("m" = "" when the input had none)."""


def fix(text):
    return bool(text) and bool(INFLECTED.search(text))


def main():
    con = sqlite3.connect(T.DB, timeout=60)
    rows = [r for r in con.execute("""SELECT t.string_id, s.en_female, t.ro_female, t.ro_male FROM translations t
                                      JOIN strings s ON s.id = t.string_id""") if fix(r[2]) or fix(r[3])]
    revs = [r for r in con.execute("""SELECT rowid, ref, reviewer, correction, comment, snapshot FROM reviews
                                      WHERE kind = 'string' AND correction <> ''""")
            if fix(r[3]) or (r[2] == "claude" and fix(json.loads(r[4] or "{}").get("m", "")))]
    # one work item per text pair: translations, then review corrections
    items = [("t", sid, en, f, m or "") for sid, en, f, m in rows]
    for rid, ref, reviewer, corr, comment, snap in revs:
        m = json.loads(comment or "{}").get("m", "") if reviewer == "claude" else ""
        items.append(("r", rid, "", corr, m))
    print(f"{len(rows)} translations + {len(revs)} review corrections to fix", flush=True)
    done, failed = {}, []
    for b in range(0, len(items), 25):
        batch = items[b:b + 25]
        masked = [(T.mask(f), T.mask(m)) for _, _, _, f, m in batch]
        lines = [{"id": i, "en": it[2][:300], "f": mf[0], **({"m": mm[0]} if it[4] else {})}
                 for i, (it, (mf, mm)) in enumerate(zip(batch, masked))]
        res = llm.chat_json(SYSTEM, json.dumps({"lines": lines}, ensure_ascii=False), think="low", model=MODEL,
                            retries=3, timeout=600, schema=llm.LINES_SCHEMA)
        got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
        for i, it in enumerate(batch):
            r = got.get(i) or {}
            nf = T.unmask(r.get("f") or "", masked[i][0][1])
            nm = T.unmask(r.get("m") or "", masked[i][1][1]) if it[4] else ""
            ok = all(not fix(new) and T.protected(new) == T.protected(old) and
                     0.6 < len(new) / max(len(old), 1) < 1.5 for new, old in ((nf, it[3]), (nm, it[4])) if old)
            (done.__setitem__((it[0], it[1]), (nf, nm, it)) if ok else failed.append(it))
        print(f"  {b + len(batch)}/{len(items)} · {len(failed)} rejected · ${llm.cost(MODEL.split(':', 1)[1]):.3f}",
              flush=True)
    for (kind, key), (nf, nm, it) in list(done.items())[:8]:
        print(f"\n{it[3][:160]}\n-> {nf[:160]}")
    for it in failed:
        print("REJECTED:", it[3][:140])
    if DRY:
        return
    now = time.time()
    snaps = {}
    for (kind, key), (nf, nm, it) in done.items():
        if kind != "t":
            continue
        con.execute("INSERT OR IGNORE INTO polish_backup VALUES (?,?,?,?,?)", (key, it[3], it[4], MODEL, now))
        con.execute("UPDATE translations SET ro_female=?, ro_male=?, created_at=? WHERE string_id=?",
                    (nf, nm, now, key))
        snaps[str(key)] = (f"{it[3]}|{it[4]}", f"{nf}|{nm}")
    for rid, ref, reviewer, corr, comment, snap in con.execute(
            "SELECT rowid, ref, reviewer, correction, comment, snapshot FROM reviews WHERE kind = 'string'").fetchall():
        if ref in snaps and snap == snaps[ref][0]:
            con.execute("UPDATE reviews SET snapshot=? WHERE rowid=?", (snaps[ref][1], rid))  # keep the fix applying
        if ("r", rid) in done:
            nf, nm, _ = done[("r", rid)]
            c = json.loads(comment or "{}") if reviewer == "claude" else None
            if c is not None and nm:
                c["m"] = nm
            con.execute("UPDATE reviews SET correction=?, comment=? WHERE rowid=?",
                        (nf, json.dumps(c, ensure_ascii=False) if c is not None else comment, rid))
    con.commit()
    print(f"saved {len(done)} fixes; {len(failed)} rejected; cost ${llm.cost(MODEL.split(':', 1)[1]):.3f}")


if __name__ == "__main__":
    main()
