"""Glossary review by Claude agents: export a chunk to review, apply the agent's decisions.

  python -I -X utf8 agent_review.py export <chunk> <of> <out.json>
      Canonical entries (variants folded) not yet decided by the user or by Claude, split into <of> chunks by
      frequency rank; includes MiniMax/Beam "noise" rejections so wrongly dropped terms can be rescued.
  python -I -X utf8 agent_review.py apply <in.json>
      in.json = [{"term", "status": "ok"|"fixed"|"flagged", "correction", "comment",
                  optional for rescues/fixes: "decision", "type", "plural", "gender"}]
      Writes reviews with reviewer='claude'. Never touches a term the user already reviewed.
  python -I -X utf8 agent_review.py summary
"""
import json
import sqlite3
import sys
import time

DB = r"D:\cp77-ro\db\strings.db"


def db():
    return sqlite3.connect(DB, timeout=60)


def export(chunk, of, out):
    con = db()
    rows = con.execute("""
        SELECT g.term, g.freq, g.is_term, g.type, g.decision, g.ro, g.gender, g.plural, g.alt, g.confidence, g.note,
               g.examples, (SELECT group_concat(v.term, ' | ') FROM glossary_draft v WHERE v.dup_of = g.term)
        FROM glossary_draft g
        WHERE g.dup_of IS NULL AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.kind = 'glossary' AND r.ref = g.term)
        ORDER BY g.freq DESC, g.term""").fetchall()
    mine = rows[chunk::of]  # interleaved so every chunk gets a mix of frequent and rare terms
    items = []
    for term, freq, is_term, typ, dec, ro, gen, pl, alt, conf, note, ex, variants in mine:
        exs = [{"en": e.get("en", ""), "ro": e.get("ro", "")} for e in json.loads(ex or "[]")]
        items.append({"term": term, "variants": variants or "", "freq": freq,
                      "proposal": None if not is_term else {"type": typ, "decision": dec, "ro": ro, "gender": gen,
                                                             "plural": pl, "alt": alt, "confidence": conf, "note": note},
                      "rejected_as_noise": not is_term, "examples": exs})
    with open(out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    print(f"chunk {chunk}/{of}: {len(items)} entries -> {out}")


def apply(path):
    con = db()
    with open(path, encoding="utf-8") as f:
        decisions = json.load(f)
    user = {r[0] for r in con.execute(
        "SELECT ref FROM reviews WHERE kind = 'glossary' AND coalesce(reviewer, 'user') = 'user'")}
    current = dict(con.execute("SELECT term, ro FROM glossary_draft"))
    done = skipped = bad = 0
    for d in decisions:
        term, status = d.get("term"), d.get("status")
        if term not in current or status not in ("ok", "fixed", "flagged"):
            bad += 1
            continue
        if term in user:
            skipped += 1
            continue
        if status == "fixed" and not (d.get("correction") or "").strip():
            bad += 1
            continue
        extra = {k: d[k] for k in ("decision", "type", "plural", "gender") if d.get(k)}
        comment = (d.get("comment") or "").strip()
        if extra:
            comment += ("\n" if comment else "") + json.dumps(extra, ensure_ascii=False)
        con.execute("""INSERT OR REPLACE INTO reviews (kind, ref, status, reason, correction, comment, updated_at,
                       snapshot, reviewer) VALUES ('glossary', ?, ?, ?, ?, ?, ?, ?, 'claude')""",
                    (term, status, "Claude", (d.get("correction") or "").strip(), comment, time.time(),
                     current[term]))
        done += 1
    con.commit()
    print(f"applied {done}, skipped {skipped} (user already decided), invalid {bad}")


def summary():
    con = db()
    for r in con.execute("""SELECT coalesce(reviewer, 'user'), status, count(*) FROM reviews
                            WHERE kind = 'glossary' GROUP BY 1, 2"""):
        print(r)
    left = con.execute("""SELECT count(*) FROM glossary_draft g WHERE g.dup_of IS NULL AND NOT EXISTS
        (SELECT 1 FROM reviews r WHERE r.kind = 'glossary' AND r.ref = g.term)""").fetchone()[0]
    print("not reviewed yet:", left)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "export":
        export(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    elif cmd == "apply":
        apply(sys.argv[2])
    else:
        summary()
