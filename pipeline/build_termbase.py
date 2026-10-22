"""Build the term base: names the game reuses across texts (people, places, quests, weapons, cyberware, clothing,
vehicles, items, perks, quickhacks...). Every term must be translated identically wherever it appears; everything
else can be translated freely.

A candidate is a short, name-like onscreen string (a display name, title, item name...). It enters the term base
when the exact English form (case-sensitive) also occurs inside other texts, or when it is a quest title / weapon /
cyberware / vehicle / perk / quickhack name. Its Romanian form is, in order: the reviewed glossary entry, the most
common existing translation of its own string, or empty (translated later by translate_termbase).

Usage: python -I -X utf8 build_termbase.py
"""
import collections
import re
import sqlite3

DB = r"D:\cp77-ro\db\strings.db"
WORD = re.compile(r"[\w'’\-]+(?:\.[\w]+)*")
SENTENCE = re.compile(r"[.!?…:;\"“”()\[\]*]+|\\n|\n|\s[-–—]\s")


def category_of(cat, skey):
    k = (skey or "").lower()
    if "journal-quests" in k and k.endswith("_title") and "emails" not in k:
        return "quest"
    for prefix, name in (("gameplay.weapons", "weapon"), ("gameplay.cyberware", "cyberware"),
                         ("gameplay.clothing", "clothing"), ("gameplay.vehicles", "vehicle"),
                         ("gameplay.quickhacks", "quickhack"), ("gameplay.rpg", "perk/skill"),
                         ("gameplay.consumables", "item"), ("gameplay.parts", "item"), ("gameplay.gadgets", "item"),
                         ("gameplay.items", "item"), ("gameplay.misc", "item"), ("gameplay.crafting", "item"),
                         ("ui.unkeyed", "item")):
        if cat.startswith(prefix):
            return name
    if "mappin" in k:
        return "place"
    if "displayname" in k or "fullname" in k or k.endswith("_name") or "localizedname" in k:
        return "name"
    if cat.startswith("story."):
        return "story"
    return None


def name_like(text):
    t = text.strip()
    if not t or len(t) > 60 or "{" in t or "<" in t or t[-1] in ".!?:,;" or "\\n" in t:
        return False
    words = t.split()
    if len(words) > 6:
        return False
    caps = sum(1 for w in words if w[:1].isupper() or any(ch.isdigit() for ch in w))
    return caps >= max(1, (len(words) + 1) // 2)  # mostly capitalized words / model codes


def main():
    con = sqlite3.connect(DB, timeout=60)
    cands = collections.defaultdict(lambda: {"cats": collections.Counter(), "ids": []})
    for sid, cat, skey, ef in con.execute("""SELECT id, category, secondary_key, en_female FROM strings
            WHERE kind = 'onscreen' AND category NOT IN ('gameplay.npc', 'ui.credits', 'ui.eula')"""):
        c = category_of(cat, skey)
        if c in ("weapon", "cyberware", "vehicle", "quickhack", "perk/skill", "clothing", "item") and not re.search(
                r"displayname|_name|name$|localizedname|title|quickhacksnames|-stats-", (skey or "").lower()) and cat != "ui.unkeyed":
            continue  # descriptions etc. of equipment are not names
        if c == "quest" and ef.strip() and not ef.startswith("!"):
            pass  # every quest title, even with ':' inside
        elif not (c and name_like(ef)):
            continue
        if c != "quest" and c in ("clothing",):
            continue  # ~2,200 clothing names are never reused elsewhere; translated freely
        if True:
            cands[ef.strip()]["cats"][c] += 1
            cands[ef.strip()]["ids"].append(sid)
    print(len(cands), "name-like candidates")

    # count exact (case-sensitive, whole-phrase) occurrences inside all game texts
    by_first = collections.defaultdict(list)
    for term in cands:
        toks = tuple(WORD.findall(term))
        if toks:
            by_first[toks[0]].append(toks)
    hits = collections.Counter()
    mid = collections.Counter()  # occurrences that are NOT at the start of a sentence: real names stay capitalized there
    lower = collections.Counter()
    for (text,) in con.execute("SELECT en_female || ' ' || en_male FROM strings WHERE category NOT IN ('gameplay.npc','ui.credits')"):
        text = re.sub(r"<[^>]+>|\{[^}]+\}", " ", text)
        for seg in SENTENCE.split(text):
            words = WORD.findall(seg)
            for i, w in enumerate(words):
                for toks in by_first.get(w, ()):
                    if tuple(words[i:i + len(toks)]) == toks:
                        hits[" ".join(toks)] += 1
                        if i > 0:
                            mid[" ".join(toks)] += 1
                if len(w) > 1 and w.islower():
                    lower[w] += 1
    terms = []
    for term, info in cands.items():
        key = " ".join(WORD.findall(term))
        own = len(info["ids"])
        refs = hits[key] - own  # occurrences outside its own strings
        cat = info["cats"].most_common(1)[0][0]
        single = len(term.split()) == 1
        if len(key) < 2 or (single and lower[term.lower()] >= hits[key]):
            continue  # an ordinary word that is just capitalized here ("Door", "Computer")
        strong = cat in ("quest", "weapon", "cyberware", "vehicle", "perk/skill", "quickhack")
        # the user asked for all equipment / weapons / quests; names and places only when other texts reuse them
        if strong or (refs >= 2 and mid[key] >= 2):
            terms.append((term, cat, refs, info["ids"]))

    # Romanian form: glossary first, then the term's own translation
    gloss = {}
    for t, ro, variants in con.execute("SELECT term, ro, variants FROM glossary_final"):
        for f in [t] + [v for v in (variants or "").split("|") if v]:
            gloss[f] = ro
    con.execute("DROP TABLE IF EXISTS termbase")
    con.execute("""CREATE TABLE termbase (term TEXT PRIMARY KEY, category TEXT, refs INTEGER, source_ids TEXT,
                   ro TEXT, ro_source TEXT, locked INTEGER DEFAULT 0)""")
    rows = []
    for term, cat, refs, ids in terms:
        ro, src = gloss.get(term), "glosar"
        if not ro:
            tr = collections.Counter(r[0] for r in con.execute(
                f"SELECT ro_female FROM translations WHERE string_id IN ({','.join(map(str, ids))}) AND qa_status <> 'fail'"))
            ro, src = (tr.most_common(1)[0][0], "traducere") if tr else ("", "")
        rows.append((term, cat, refs, ",".join(map(str, ids[:50])), ro, src))
    con.executemany("INSERT INTO termbase (term, category, refs, source_ids, ro, ro_source) VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    for r in con.execute("SELECT category, count(*), sum(ro <> ''), sum(refs) FROM termbase GROUP BY 1 ORDER BY 2 DESC"):
        print(r)
    print("total", con.execute("SELECT count(*) FROM termbase").fetchone()[0])


if __name__ == "__main__":
    main()
