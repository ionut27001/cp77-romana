"""Spot-check translated lines with Claude agents: export a sample, apply the agent's fixes.

  python -I -X utf8 line_review.py export <name> <n> <sql-filter> <out.json>
      Sample of translated units (one string per distinct English text), in file/scene order, matching the SQL
      filter on strings s / translations t, e.g. "s.category LIKE 'ui.%'". Lines already reviewed are skipped.
  python -I -X utf8 line_review.py apply <in.json>
      in.json = [{"id": <string id>, "status": "ok"|"fixed", "f": "<fixed text>", "m": "<fixed male-V text>",
                  "comment": "<why>"}]  — fixes are applied to every string with the same English text.
      Never touches lines the user reviewed. pack.py uses the fixes.
"""
import json
import sqlite3
import sys
import time

DB = r"D:\cp77-ro\db\strings.db"


def export(name, n, where, out):
    con = sqlite3.connect(DB, timeout=60)
    rows = con.execute(f"""
        SELECT min(s.id), s.category, s.depot_path, s.en_female, s.en_male, s.pl_gendered, t.ro_female, t.ro_male,
               t.qa_status, t.qa_notes, min(s.ord)
        FROM strings s JOIN translations t ON t.string_id = s.id
        WHERE ({where}) AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.kind = 'string' AND r.ref = CAST(s.id AS TEXT))
        GROUP BY s.en_female, s.en_male, s.category
        ORDER BY random() LIMIT {int(n) // 6}""").fetchall()
    # take whole runs of consecutive lines around random anchors, so dialogue is judged in context
    items, seen = [], set()
    for sid, cat, depot, *_ in rows:
        for r in con.execute("""SELECT s.id, s.category, s.depot_path, s.en_female, s.en_male, s.pl_gendered,
                    t.ro_female, t.ro_male, t.qa_status, t.qa_notes, s.secondary_key
                FROM strings s JOIN translations t ON t.string_id = s.id
                WHERE s.depot_path = ? AND s.ord BETWEEN (SELECT ord FROM strings WHERE id = ?) - 2
                      AND (SELECT ord FROM strings WHERE id = ?) + 3 ORDER BY s.ord""", (depot, sid, sid)):
            if r[0] in seen or (r[3], r[4]) in {(i["en"], i["en_m"]) for i in items}:
                continue
            seen.add(r[0])
            items.append({"id": r[0], "category": r[1], "file": r[2].split("\\en-us\\")[-1],
                          "key": r[10] or "", "en": r[3], "en_m": r[4], "v_gendered": bool(r[5] or r[4]),
                          "ro_f": r[6], "ro_m": r[7], "qa": r[8], "qa_notes": r[9]})
    with open(out, "w", encoding="utf-8") as f:
        json.dump(items[:int(n)], f, ensure_ascii=False, indent=1)
    print(f"{name}: {len(items[:int(n)])} lines -> {out}")


def apply(path):
    con = sqlite3.connect(DB, timeout=60)
    decisions = json.load(open(path, encoding="utf-8"))
    user = {r[0] for r in con.execute(
        "SELECT ref FROM reviews WHERE kind = 'string' AND coalesce(reviewer, 'user') = 'user'")}
    done = bad = 0
    for d in decisions:
        src = con.execute("SELECT en_female, en_male, category FROM strings WHERE id = ?", (d.get("id"),)).fetchone()
        if not src or d.get("status") not in ("ok", "fixed"):
            bad += 1
            continue
        male_only = not src[0].strip() and src[1].strip()  # line exists only for male V
        if d["status"] == "fixed" and not (d.get("f") or "").strip() and not (male_only and (d.get("m") or "").strip()):
            bad += 1
            continue
        same = con.execute("""SELECT s.id, t.ro_female, t.ro_male FROM strings s JOIN translations t ON t.string_id = s.id
                              WHERE s.en_female = ? AND s.en_male = ? AND s.category = ?""", src).fetchall()
        for sid, rf, rm in same:
            if str(sid) in user:
                continue
            con.execute("""INSERT OR REPLACE INTO reviews (kind, ref, status, reason, correction, comment, updated_at,
                           snapshot, reviewer) VALUES ('string', ?, ?, 'Claude', ?, ?, ?, ?, 'claude')""",
                        (str(sid), d["status"], (d.get("f") or "").strip(),
                         json.dumps({"m": (d.get("m") or "").strip(), "why": d.get("comment", "")}, ensure_ascii=False),
                         time.time(), f"{rf}|{rm or ''}"))
        done += 1
    con.commit()
    print(f"applied {done} decisions, invalid {bad}")


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(*sys.argv[2:6])
    else:
        apply(sys.argv[2])
