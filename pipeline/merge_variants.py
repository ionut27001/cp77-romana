"""Fold spelling variants of the same glossary term into one entry.

"Arasaka's", "ARASAKA", "Arasakas" -> dup_of = "Arasaka" (the most frequent drafted form, preferring real terms).
Variants stay in glossary_draft but are hidden from review; the canonical entry's decision covers them.
Safe to re-run (recomputes dup_of for everything drafted so far).

Usage: python -I -X utf8 merge_variants.py
"""
import collections
import re
import sqlite3

DB = r"D:\cp77-ro\db\strings.db"
NO_MERGE = {"jack"}  # "Jack" (a name) and "jack" (jack in) are different terms


def key(term):
    return re.sub(r"['’]s$", "", term.strip()).lower()


def main():
    con = sqlite3.connect(DB, timeout=60)
    if "dup_of" not in [r[1] for r in con.execute("PRAGMA table_info(glossary_draft)")]:
        con.execute("ALTER TABLE glossary_draft ADD COLUMN dup_of TEXT")
    rows = con.execute("SELECT term, freq, is_term, ro FROM glossary_draft").fetchall()
    groups = collections.defaultdict(list)
    for term, freq, is_term, ro in rows:
        k = key(term)
        if k in NO_MERGE:
            k = term  # keep case-distinct forms apart
        groups[k].append((term, freq, is_term, term == (ro or '').strip()))
    for k in list(groups):  # fold plurals into an existing singular group
        for sing in ([k[:-1]] if k.endswith("s") else []) + ([k[:-3] + "y"] if k.endswith("ies") else []):
            if sing in groups and sing != k and k in groups:
                groups[sing] += groups.pop(k)
                break
    updates = []
    for members in groups.values():
        canon = max(members, key=lambda m: (m[2], m[3], not m[0].islower(), m[1]))[0]  # real term, spelled as proposed, capitalized, frequent
        for term, *_ in members:
            updates.append((None if term == canon else canon, term))
    con.executemany("UPDATE glossary_draft SET dup_of = ? WHERE term = ?", updates)
    con.commit()
    n = sum(1 for d, _ in updates if d)
    print(f"{len(rows)} drafted terms: {n} folded into {len(rows) - n} entries")


if __name__ == "__main__":
    main()
