"""Draft the Romanian glossary from term_candidates with MiniMax, then export it for review.

Stages (each resumable, results kept in strings.db):
  jargon  - ask the LLM which frequent lowercase words are Night City slang/jargon -> term_candidates
  draft   - classify every candidate and propose a Romanian rendering -> glossary_draft
  export  - write D:\\cp77-ro\\glossary\\glossary_draft.csv (opens in Excel)

Usage: python -I -X utf8 draft_glossary.py [jargon|draft|export|all]
"""
import concurrent.futures as cf
import csv
import json
import pathlib
import re
import sqlite3
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402

DB = r"D:\cp77-ro\db\strings.db"
OUT = pathlib.Path(r"D:\cp77-ro\glossary")
MIN_FREQ = 5
BATCH = 12
WORKERS = 2
THINK = True  # bool, or a level string for models that support it ("low"/"medium"/"high")

JARGON_SYSTEM = """You help localize Cyberpunk 2077. You get a list of lowercase words that occur often in the game's text.
Return {"jargon": [...]} with ONLY the words that are Cyberpunk / Night City slang, invented tech or lore terms,
or foreign (Spanish, Japanese, Haitian Creole...) words used as street slang — e.g. choom, preem, gonk, eddies,
nova, delta, chooms, ripperdoc, cyberdeck, chica, hermano. Exclude normal English vocabulary, ordinary profanity,
contractions and spelling-of-accent forms like gonna, wanna, lookin'."""

DRAFT_SYSTEM = """You are the terminology lead for a high-quality Romanian fan localization of Cyberpunk 2077 (+ Phantom Liberty).
For each candidate term you get its frequency, a source tag, and example lines in English with the official Polish
translation of the same line (shows how CDPR's own localizers treated the term).

LORE PRIMER (facts — do not contradict them):
- Relic: Arasaka's experimental biochip that stores a personality engram; V carries it with Johnny Silverhand's
  engram. A key story term (capitalized "Relic"), never an ordinary word.
- Blackwall: NetWatch's barrier/firewall that walls off rogue AIs beyond the old Net. Not a place to visit.
- Samurai: Johnny Silverhand's rock band; Johnny also calls V "Samurai". Soulkiller = Arasaka program that copies
  minds into engrams; Mikoshi = Arasaka's engram vault; engram / construct = digitized personality.
- Slang: choom(s) = friend/buddy/mate; preem = great/top-quality; nova = cool; delta = leave/get going;
  gonk = idiot; flatline = kill/die; eddies = eurodollars (money); corpo = corporate person; merc = mercenary;
  fixer = broker who hands out gigs; ripperdoc/ripper = street cyberware surgeon; netrunner = hacker who dives the
  Net; braindance/BD = recorded sensory experience; chrome = cyberware; borg = heavily cyberized person;
  cyberpsycho = person driven violently insane by cyberware; scav = member of organ-harvesting scavenger gangs.
- NUSA = New United States of America. FIA = Federal Intelligence Agency (NUSA). NCPD = Night City police;
  MaxTac = NCPD unit that hunts cyberpsychos; Trauma Team = armed private medical response.
- Phantom Liberty: Dogtown = walled-off part of Pacifica ruled by Kurt Hansen's militia **Barghest** (an armed
  group, not a product). Songbird = So Mi, a NUSA netrunner. Reed = Solomon Reed, FIA agent.
- Delamain = AI-run taxi company (and its AI). Afterlife = mercenary bar. Aldecaldos = a nomad clan.
- Lowercase candidates that are really proper names (netwatch, maelstrom) get the proper capitalization in "ro".
- Romanian morphology must be correct: nomad -> plural "nomazi", fixer -> "fixeri", netrunner -> "netrunneri".

Decide, per term:
- is_term: false if it is noise (ordinary word, sentence fragment, UI verb like "Wait"/"Yes", a capitalised normal
  word). Ordinary words do NOT belong in the glossary.
- type: person | nickname | place | district | venue | corporation | brand | product | gang | organization |
        slang | lore_tech | game_mechanic | ui_label | quest | other
- decision: keep (leave English form) | translate | adapt (keep root, Romanian spelling/morphology)
- ro: the canonical Romanian form (singular, nominative, unarticulated). For keep, repeat the English form.
- gender: Romanian grammatical gender used for agreement and articles: m | f | n | - (not applicable / proper name
  used without article). Proper names of corps/gangs are usually '-' and get a head noun ("corporația Arasaka").
- plural: Romanian plural if it is a countable noun (e.g. "netrunneri"), else "".
- alt: one alternative rendering worth considering, or "".
- confidence: high | medium | low  (low = a human must decide)
- note: short usage note in Romanian or English (declension with hyphen "Arasaka-ului"? head noun? register?).

Default policy (follow unless clearly wrong):
- People, nicknames, AIs, characters: keep (Johnny Silverhand, Jackie, Songbird, Rogue, Delamain).
- Night City districts, sub-districts, venues, bars, clubs, streets: keep. A landmark whose head is a plain noun
  translates only the head noun: "Arasaka Tower" -> "Turnul Arasaka", "Afterlife" stays "Afterlife".
- Corporations, brands, product/model names, weapon and vehicle model names: keep.
- Gangs and organizations: keep the name (Tyger Claws, Voodoo Boys, Maelstrom, NCPD, MaxTac, NetWatch, NUSA, FIA);
  note the head noun to use ("gașca Valentinos", "agenții NetWatch").
- Night City slang (choom, preem, gonk, nova, delta, eddies, corpo, merc, fixer, ripperdoc, netrunner,
  braindance, chrome, borg, scav...): KEEP the English word (the human decided: Romglish, like the original),
  only give it Romanian morphology ("choomul", "choomii", "eddie-uri", "gonkule!" for vocative, "corpoii").
  Put a Romanian equivalent in alt only as information. Translate a slang word only if it is a plain
  English word whose literal meaning is meant (e.g. "chrome" meaning the metal).
- Game mechanics and UI labels (attributes, stats, perks, menus, item types, damage types): translate, short and
  consistent, the way a professional Romanian game UI would read. Abbreviations (INT, TECH, REF) get Romanian
  abbreviations only if natural, else keep.
- Setting: the year is 2077, a high-tech, hyper-commercial, English-dominated American megacity. The Romanian must
  sound like how young Romanians talk and write TODAY or later: urban, tech-savvy, gamer register.
- NO archaisms, ever. No bookish, folkloric, regional-rural or old-fashioned words (e.g. never "a se purcede",
  "domnia-ta", "nicicând", "vrăjmaș", "ostaș", "hrisov", "zapis", "ceaun", "lefter"-style flavor for tech). If the
  only Romanian equivalent sounds old or literary, prefer the English term instead.
- Some Romglish is welcome and natural (like Romanian gamers/IT people speak): English tech and street words with
  Romanian morphology are fine — "un netrunner", "netrunnerii", "hack-uit", "upgrade", "implantul de cyberware",
  "gig-ul", "skill-uri". Use a hyphen before Romanian endings when the English spelling ends in a letter that
  makes the stem unclear ("gig-ul", "BD-ul", "AV-ul"). Do not force awkward calques of established gamer terms.
- Use correct Romanian diacritics with comma below (ș, ț) and ă, â, î.

- examples_ro: translate each English example line of the term into natural Romanian, using your proposed
  rendering of the term (same order as the examples; the human judges the term by how these lines sound).
- The Polish lines are reference only. NEVER output Polish words; every "ro" and "examples_ro" is Romanian.
- Profanity (fuck, shit, damn...) is not a glossary term: is_term false. It is handled by the dialogue style guide.

Return {"items": [{"term","is_term","type","decision","ro","gender","plural","alt","confidence","note",
"examples_ro"}, ...]} with exactly one item per input term, same spelling of "term"."""

lock = threading.Lock()
POLISH = re.compile("[łŁżŻźŹśŚćĆńŃęĘąĄ]")


def db():
    return sqlite3.connect(DB, timeout=60)


def set_state(stage, total, done, inflight, note=None):
    """Progress row the review UI shows while a stage runs (note=None keeps the previous note)."""
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS run_state (stage TEXT PRIMARY KEY, total INTEGER, done INTEGER,
                 inflight INTEGER, started_at REAL, updated_at REAL, note TEXT)""")
    now = time.time()
    c.execute("""INSERT INTO run_state VALUES (?,?,?,?,?,?,?) ON CONFLICT(stage) DO UPDATE SET total=excluded.total,
                 done=excluded.done, inflight=excluded.inflight, updated_at=excluded.updated_at,
                 note=coalesce(excluded.note, run_state.note),
                 started_at=CASE WHEN excluded.note IS NOT NULL AND excluded.done = 0 THEN excluded.started_at
                                 ELSE run_state.started_at END""",
              (stage, total, done, inflight, now, now, note))
    c.commit()
    c.close()


def examples_for(con, term, ids, n=2):
    cols = "id, en_female, pl_female, depot_path, category, coalesce(secondary_key, key)"
    rows = []
    if ids:
        rows = con.execute(f"SELECT {cols} FROM strings WHERE id IN ({ids}) LIMIT {n}").fetchall()
    if len(rows) < n:
        rows += con.execute(
            f"""SELECT {cols} FROM strings WHERE instr(en_female, ?) > 0
               AND category NOT IN ('gameplay.npc','ui.credits','ui.eula') ORDER BY length(en_female) LIMIT ?""",
            (term, n - len(rows))).fetchall()
    return [{"id": i, "en": e[:220], "pl": (p or "")[:220], "file": d, "category": c, "key": k}
            for i, e, p, d, c, k in rows]


def stage_jargon():
    con = db()
    toks = [t for (t,) in con.execute(
        "SELECT tok FROM lower_tokens WHERE tok NOT IN (SELECT lower(term) FROM term_candidates) ORDER BY freq DESC")]
    chunks = [toks[i:i + 400] for i in range(0, len(toks), 400)]
    found = set()
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for res in ex.map(lambda c: llm.chat_json(JARGON_SYSTEM, json.dumps(c), think=THINK), chunks):
            found.update(w for w in res.get("jargon", []) if w in toks)
    freq = dict(con.execute("SELECT tok, freq FROM lower_tokens"))
    con.executemany("INSERT OR IGNORE INTO term_candidates VALUES (?, 'slang-llm', ?, '')",
                    [(w, freq.get(w, 0)) for w in sorted(found)])
    con.commit()
    print(f"jargon: {len(found)} words added")


def stage_draft():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS glossary_draft (
        term TEXT PRIMARY KEY, source TEXT, freq INTEGER, is_term INTEGER, type TEXT, decision TEXT, ro TEXT,
        gender TEXT, plural TEXT, alt TEXT, confidence TEXT, note TEXT, examples TEXT,
        batch_secs REAL, created_at REAL, model TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS llm_log (
        at REAL, stage TEXT, items INTEGER, answered INTEGER, secs REAL, error TEXT)""")
    todo = con.execute("""SELECT term, source, freq, example_ids FROM term_candidates
        WHERE (freq >= ? OR source LIKE 'slang%') AND term NOT IN (SELECT term FROM glossary_draft)
        ORDER BY freq DESC""", (MIN_FREQ,)).fetchall()
    items = [{"term": t, "source": s, "freq": f, "ids": ids} for t, s, f, ids in todo]
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    print(f"draft: {len(items)} terms in {len(batches)} batches")
    state = {"done": 0, "inflight": 0}
    set_state("glossary", len(items), 0, 0, f"{len(batches)} loturi x {BATCH} termeni, {WORKERS} în paralel")

    def log(n, ok, secs, err=""):
        with lock:
            c = db()
            c.execute("INSERT INTO llm_log VALUES (?, 'glossary', ?, ?, ?, ?)", (time.time(), n, ok, secs, err))
            c.commit()

    def run(batch):
        t0 = time.time()
        with lock:
            state["inflight"] += 1
            set_state("glossary", len(items), state["done"], state["inflight"])
        try:
            return run_batch(batch, t0)
        finally:
            with lock:
                state["inflight"] -= 1
                set_state("glossary", len(items), state["done"], state["inflight"])

    def run_batch(batch, t0):
        c = db()
        for it in batch:
            it["examples"] = examples_for(c, it["term"], it["ids"])
        c.close()
        prompt = [{k: it[k] for k in ("term", "source", "freq")} |
                  {"examples": [{"en": e["en"], "pl": e["pl"]} for e in it["examples"]]} for it in batch]
        try:
            res = llm.chat_json(DRAFT_SYSTEM, json.dumps(prompt, ensure_ascii=False), think=THINK)
        except RuntimeError as e:
            log(len(batch), 0, time.time() - t0, str(e))
            raise
        secs = time.time() - t0
        got = {r.get("term"): r for r in res.get("items", []) if isinstance(r, dict)}
        rows = []
        for it in batch:
            r = got.get(it["term"])
            if not r:
                continue  # missing from the answer; picked up on the next run
            ex_ro = r.get("examples_ro") or []
            for i, e in enumerate(it["examples"]):
                e["ro"] = ex_ro[i] if i < len(ex_ro) and isinstance(ex_ro[i], str) else ""
            if POLISH.search(" ".join([str(r.get("ro", ""))] + [e["ro"] for e in it["examples"]])):
                r["confidence"] = "low"  # Polish leaked from the reference lines
                r["note"] = "⚠ conține text polonez — verifică. " + str(r.get("note", ""))
            rows.append((it["term"], it["source"], it["freq"], int(bool(r.get("is_term"))), r.get("type", ""),
                         r.get("decision", ""), r.get("ro", ""), r.get("gender", ""), r.get("plural", ""),
                         r.get("alt", ""), r.get("confidence", ""), r.get("note", ""),
                         json.dumps(it["examples"], ensure_ascii=False), secs, time.time(), llm.MODEL))
        with lock:
            c = db()
            c.executemany("""INSERT OR REPLACE INTO glossary_draft (term, source, freq, is_term, type, decision, ro, gender,
                plural, alt, confidence, note, examples, batch_secs, created_at, model)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            c.commit()
            state["done"] += len(rows)
        log(len(batch), len(rows), secs)
        return len(rows), len(batch)

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for fut in cf.as_completed([ex.submit(run, b) for b in batches]):
            try:
                fut.result()
            except (RuntimeError, sqlite3.Error) as e:
                print("batch failed:", e, flush=True)
            print(f"  {state['done']}/{len(items)}", flush=True)
    set_state("glossary", len(items), state["done"], 0, "terminat")


TYPE_ORDER = ["person", "nickname", "slang", "lore_tech", "game_mechanic", "ui_label", "gang", "organization",
              "corporation", "brand", "product", "district", "place", "venue", "quest", "other"]


def stage_export():
    OUT.mkdir(exist_ok=True)
    con = db()
    rows = con.execute("""SELECT type, term, freq, decision, ro, gender, plural, alt, confidence, note, examples
                          FROM glossary_draft WHERE is_term = 1""").fetchall()
    rows.sort(key=lambda r: (TYPE_ORDER.index(r[0]) if r[0] in TYPE_ORDER else 99, -r[2]))
    path = OUT / "glossary_draft.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")  # ';' so Excel with Romanian/European locale splits columns
        w.writerow(["type", "term_en", "freq", "decision", "ro", "gender", "plural", "alt", "confidence", "note",
                    "example_en", "example_ro", "YOUR_DECISION"])
        for r in rows:
            ex = json.loads(r[10] or "[]")
            w.writerow(list(r[:10]) + [ex[0]["en"] if ex else "", ex[0].get("ro", "") if ex else "", ""])
    noise = con.execute("SELECT count(*) FROM glossary_draft WHERE is_term = 0").fetchone()[0]
    print(f"export: {len(rows)} terms -> {path} ({noise} rejected as noise)")


if __name__ == "__main__":
    # optional: --model beam:cloud --think medium --workers 1 --batch 12
    args = sys.argv[1:]
    opt = {args[i][2:]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
    llm.MODEL = opt.get("model", llm.MODEL)
    THINK = {"true": True, "false": False}.get(opt.get("think", "true"), opt.get("think"))
    WORKERS = int(opt.get("workers", WORKERS))
    BATCH = int(opt.get("batch", BATCH))
    stage = args[0] if args and not args[0].startswith("--") else "all"
    for name, fn in (("jargon", stage_jargon), ("draft", stage_draft), ("export", stage_export)):
        if stage in (name, "all"):
            fn()
