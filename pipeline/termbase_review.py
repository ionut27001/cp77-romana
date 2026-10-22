"""Curate the term base with Claude agents.

  python -I -X utf8 termbase_review.py export <chunk> <of> <out.json>
      Entries with term, category, refs (uses outside its own strings), current Romanian (ro, ro_source),
      the glossary entry if any, and up to 3 real lines that use the term.
  python -I -X utf8 termbase_review.py apply <in.json>
      in.json = [{"term", "keep": true|false, "category", "ro", "note"}] — keep=false drops it from the term base
      (it is then translated freely). Kept entries are locked: the translator must use "ro" everywhere.
"""
import json
import sqlite3
import sys

DB = r"D:\cp77-ro\db\strings.db"


def db():
    con = sqlite3.connect(DB, timeout=60)
    cols = [r[1] for r in con.execute("PRAGMA table_info(termbase)")]
    for c, t in (("status", "TEXT"), ("note", "TEXT")):
        if c not in cols:
            con.execute(f"ALTER TABLE termbase ADD COLUMN {c} {t}")
    return con


def export(chunk, of, out):
    con = db()
    gloss = {t: (ro, note) for t, ro, note in con.execute("SELECT term, ro, note FROM glossary_final")}
    rows = con.execute("SELECT term, category, refs, ro, ro_source FROM termbase WHERE status IS NULL ORDER BY refs DESC, term").fetchall()
    items = []
    for term, cat, refs, ro, src in rows[chunk::of]:
        ex = [r[0][:160] for r in con.execute(
            "SELECT en_female FROM strings WHERE instr(en_female, ?) > 0 AND en_female <> ? AND category NOT IN ('gameplay.npc') LIMIT 3",
            (term, term))]
        g = gloss.get(term)
        items.append({"term": term, "category": cat, "refs": refs, "ro": ro, "ro_source": src,
                      "glossary": f"{g[0]} — {g[1][:120]}" if g else "", "used_in": ex})
    json.dump(items, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"chunk {chunk}/{of}: {len(items)} -> {out}")


def apply(path):
    con = db()
    n = bad = 0
    for d in json.load(open(path, encoding="utf-8")):
        if not con.execute("SELECT 1 FROM termbase WHERE term = ?", (d.get("term"),)).fetchone():
            bad += 1
            continue
        if d.get("keep"):
            if not (d.get("ro") or "").strip():
                bad += 1
                continue
            con.execute("""UPDATE termbase SET status = 'keep', locked = 1, ro = ?, category = coalesce(?, category),
                           ro_source = 'claude', note = ? WHERE term = ?""",
                        (d["ro"].strip(), d.get("category"), d.get("note", ""), d["term"]))
        else:
            con.execute("UPDATE termbase SET status = 'drop', locked = 0, note = ? WHERE term = ?",
                        (d.get("note", ""), d["term"]))
        n += 1
    con.commit()
    print(f"applied {n}, invalid {bad}")
    print(con.execute("SELECT status, count(*) FROM termbase GROUP BY 1").fetchall())


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    else:
        apply(sys.argv[2])
