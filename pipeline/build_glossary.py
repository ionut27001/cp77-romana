"""Resolve the glossary the translator uses: drafts + Claude reviews + the user's reviews -> glossary_final.

Priority per entry: user's decision > Claude's fix > Claude's recommendation (still open for the user) >
draft. Variants (Arasaka's, ARASAKA...) map to their canonical entry. Re-run any time; translate.py reloads it.
Entries still open for the user get status 'provisional' so their lines can be re-translated once decided.

Usage: python -I -X utf8 build_glossary.py
"""
import json
import sqlite3

DB = r"D:\cp77-ro\db\strings.db"

# The user rejected English for these but gave no form: give the translator the direction instead.
USER_DIRECTION = {
    "gonk": ("fraier", "insultă — alege după ton: fraier / bou / tâmpit / idiot; NICIODATĂ «gonk»"),
    "preem": ("beton", "adjectiv de laudă — beton / marfă / de top / meseriaș; NICIODATĂ «preem»"),
    "scav": ("hienă", "membru al bandelor care recoltează organe: hienă / hiene; NICIODATĂ «scav»"),
    "scavs": ("hiene", "membri ai bandelor care recoltează organe: hiene; NICIODATĂ «scavs»"),
}


def extra_from_comment(comment):
    """Claude's apply() appends a JSON line with decision/type/plural/gender overrides."""
    if comment and "\n{" in comment:
        try:
            return json.loads(comment[comment.index("\n{") + 1:])
        except ValueError:
            pass
    return {}


def main():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("DROP TABLE IF EXISTS glossary_final")
    con.execute("""CREATE TABLE glossary_final (
        term TEXT PRIMARY KEY, variants TEXT, type TEXT, decision TEXT, ro TEXT, gender TEXT, plural TEXT,
        note TEXT, status TEXT, freq INTEGER)""")
    rows = con.execute("""
        SELECT g.term, g.type, g.decision, g.ro, g.gender, g.plural, g.note, g.is_term, g.freq,
               (SELECT group_concat(v.term, '|') FROM glossary_draft v WHERE v.dup_of = g.term),
               r.status, coalesce(r.reviewer, 'user'), r.correction, r.comment
        FROM glossary_draft g LEFT JOIN reviews r ON r.kind = 'glossary' AND r.ref = g.term
             AND (r.snapshot IS NULL OR r.snapshot = g.ro)
        WHERE g.dup_of IS NULL""").fetchall()
    out = []
    for (term, typ, dec, ro, gen, pl, note, is_term, freq, variants, status, reviewer, corr, comment) in rows:
        extra = extra_from_comment(comment)
        draft_ro = ro
        clean_comment = (comment or "").split("\n{")[0].strip()
        if reviewer == "user" and status:
            if status == "ok":
                st = "final"
            elif corr:
                ro, st = corr, "final"
            elif term.lower() in USER_DIRECTION:
                ro, note = USER_DIRECTION[term.lower()]
                dec, st = "translate", "final"
            else:
                st = "provisional"  # user flagged it without a fix: keep the draft for now
            if clean_comment:
                note = f"{note or ''} | utilizator: {clean_comment}".strip(" |")
        elif reviewer == "claude" and status == "fixed":
            ro, st = corr, "final"
            note = clean_comment or note
        elif reviewer == "claude" and status == "flagged":
            ro, st = corr or ro, "provisional"
            note = clean_comment or note
        elif reviewer == "claude" and status == "ok":
            st = "final"
        else:
            st = "draft"
        if not is_term and not (reviewer == "claude" and status == "fixed"):
            continue  # noise, not rescued
        if ro != draft_ro:
            gen, pl = "", ""  # the draft's grammar belonged to the replaced word
        dec, typ = extra.get("decision", dec), extra.get("type", typ)
        gen, pl = extra.get("gender", gen), extra.get("plural", pl)
        out.append((term, variants or "", typ, dec, ro, gen, pl, note or "", st, freq))
    con.executemany("INSERT INTO glossary_final VALUES (?,?,?,?,?,?,?,?,?,?)", out)
    con.commit()
    for r in con.execute("SELECT status, count(*) FROM glossary_final GROUP BY status"):
        print(r)


if __name__ == "__main__":
    main()
