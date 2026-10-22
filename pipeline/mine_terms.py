"""Mine glossary candidates from strings.db into the `term_candidates` table.

Sources:
  proper   - capitalised word sequences seen mid-sentence (people, places, corps, gangs, brands)
  ui       - short UI / RPG labels that other strings refer to (attributes, stats, menu names)
  slang    - frequent lowercase words that are Night City jargon (hand seeds + LLM-flagged later)
Random NPC first/last names (Gameplay-NPC-EthnicNames-*) are excluded: they are never translated.

Usage: python -I -X utf8 mine_terms.py
"""
import collections
import re
import sqlite3

DB = r"D:\cp77-ro\db\strings.db"

# Known Night City jargon; the LLM pass adds more from the frequent-lowercase list.
SLANG_SEEDS = """choom chooms eddies eddie gonk gonks preem nova delta flatline flatlined flatlining chrome chromed
borg netrunner netrunners netrunning fixer fixers ripperdoc ripper braindance bd bds gig gigs merc mercs corpo corpos
nomad nomads nomadic street kid cyberpsycho cyberpsychos cyberpsychosis scav scavs gato chica hermano cabrón jefe vato
nethead jack jacked jacking zeroed zero frack frackin fuck fucking samurai biochip relic cyberdeck deck daemon daemons
quickhack quickhacks breach netwatch blackwall ice ai ais construct engram soulkiller mox moxes tyger tygers animals
valentino valentinos wraith wraiths raffen sixth street maelstrom voodoo boys scavenger scavengers solo solos techie
edgerunner edgerunners lifepath nusa dogtown barghest kurt hansen""".split()

STOP = set("""I I'm I'll I've I'd The A An And But Or If So Then This That These Those It It's Its He She We You They
What Why How Who Where When Yes No Not Okay OK Oh Hey Well Just Now Here There Let Let's Look Come Go Get Got Mr Mrs Ms
Miss Dr Sir Ma'am Uh Um Hm Huh Ah Yeah Yep Nope Shit Fuck Damn Christ God Jesus Please Thanks Thank Sorry Wait Listen
Good Great Right Sure Fine Alright All My Your His Her Our Their One Two Three Don't Can't Won't Didn't Isn't Ain't
Gotta Gonna Wanna Kinda See Take Give Tell Know Think Need Want Make Keep Stay Stop Leave Move Run Shut""".split())

CAP_SEQ = re.compile(r"(?<![\w'’])((?:[A-Z][\w'’\-\.]*[\w])(?:\s+(?:of|the|de|la|del|von|van|y)?\s*[A-Z][\w'’\-]*[\w]){0,3})")
SENT_START = re.compile(r"(^|[.!?…:\"“\-–—]\s*)$")
TAG = re.compile(r"<[^>]+>|\{[^}]+\}")
WORD = re.compile(r"[\w'’\-]+")


def proper_candidates(rows):
    count = collections.Counter()
    examples = collections.defaultdict(list)
    for sid, text in rows:
        text = TAG.sub(" ", text)
        for m in CAP_SEQ.finditer(text):
            term = m.group(1).strip(" .")
            words = term.split()
            if SENT_START.search(text[:m.start()]):  # sentence start: drop a leading stopword only
                if words[0] in STOP:
                    words = words[1:]
                    if not words:
                        continue
                    term = " ".join(words)
                elif len(words) == 1:
                    continue  # a single capitalised word at sentence start is not evidence
            if term in STOP or len(term) < 2 or term.isupper() and len(term) > 12:
                continue
            count[term] += 1
            if len(examples[term]) < 3:
                examples[term].append(sid)
    return count, examples


def main():
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS term_candidates")
    con.execute("""CREATE TABLE term_candidates (
        term TEXT PRIMARY KEY, source TEXT, freq INTEGER, example_ids TEXT)""")
    rows = con.execute("""SELECT id, en_female || ' ' || en_male FROM strings
                          WHERE category NOT IN ('gameplay.npc', 'ui.credits', 'ui.eula')""").fetchall()

    count, examples = proper_candidates(rows)
    # drop sub-phrases that only ever occur inside a longer candidate ("Silverhand" alone is still kept if frequent)
    proper = {t: n for t, n in count.items() if n >= 4}

    # short UI/RPG labels
    labels = con.execute("""SELECT DISTINCT en_female FROM strings
        WHERE kind='onscreen' AND words BETWEEN 1 AND 4 AND (category LIKE 'ui.%' OR category IN
        ('gameplay.rpg','gameplay.statuseffects','gameplay.quickhacks','gameplay.cyberware','gameplay.inputhints',
         'gameplay.crafting','gameplay.scanning','gameplay.items'))
        AND category NOT IN ('ui.credits','ui.unkeyed')""").fetchall()
    corpus = "\n".join(t for _, t in rows)
    titles = {TAG.sub("", lab).strip(" :.") for (lab,) in labels}
    by_first = collections.defaultdict(list)  # first token -> label token tuples
    for lab in titles:
        if len(lab) < 3 or not re.search("[A-Za-z]", lab) or lab.startswith("!"):
            continue
        if lab.isupper() and lab.title() in titles:
            continue  # ALL CAPS copy of a Title Case label
        toks = tuple(WORD.findall(lab))
        if toks:
            by_first[toks[0]].append(toks)
    hits = collections.Counter()
    words = WORD.findall(corpus)
    for i, w in enumerate(words):
        for toks in by_first.get(w, ()):
            if tuple(words[i:i + len(toks)]) == toks:
                hits[toks] += 1
    ui = {" ".join(t): n for t, n in hits.items() if n >= 3}
    corpus = corpus.lower()

    # frequent lowercase tokens (LLM decides which are jargon) + seeds
    tok = collections.Counter(re.findall(r"\b[a-z][a-z'\-]{2,}\b", corpus))
    seeds = {w: tok.get(w, 0) for w in SLANG_SEEDS}

    out = {}
    for t, n in proper.items():
        out[t] = ("proper", n, examples[t])
    for t, n in ui.items():
        out.setdefault(t, ("ui", n, []))
    for t, n in seeds.items():
        out.setdefault(t, ("slang", n, []))
    con.executemany("INSERT INTO term_candidates VALUES (?,?,?,?)",
                    [(t, s, n, ",".join(map(str, ex))) for t, (s, n, ex) in out.items()])
    # the 4000 most frequent lowercase words, for the LLM jargon filter
    con.execute("DROP TABLE IF EXISTS lower_tokens")
    con.execute("CREATE TABLE lower_tokens (tok TEXT PRIMARY KEY, freq INTEGER)")
    con.executemany("INSERT INTO lower_tokens VALUES (?,?)", tok.most_common(4000))
    con.commit()
    print({s: sum(1 for v in out.values() if v[0] == s) for s in ("proper", "ui", "slang")})


if __name__ == "__main__":
    main()
