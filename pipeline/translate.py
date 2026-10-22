"""Translate all game text into Romanian: strings.db -> translations.

- Identical source texts in the same domain are translated once (units) and applied to every string id.
- Batches follow the game files (scene order for dialogue, key order for UI/items) so the model sees context.
- Each batch gets the domain style guide + only the glossary entries that occur in it.
- Every line is QA-checked (placeholders/tags, Polish leaks, banned glossary forms, untranslated text);
  failures are retried on the other engine with the QA notes.
- Beam and MiniMax pull from the same queue (Beam is ~10x faster, MiniMax adds a second opinion/capacity).
Resumable: units that already have translations are skipped (use --redo-provisional after glossary decisions).

Usage: python -I -X utf8 translate.py [--only p0,p1] [--max-batches N] [--beam 3] [--minimax 1] [--batch 25]
"""
import collections
import concurrent.futures as cf
import json
import pathlib
import queue
import re
import sqlite3
import sys
import threading
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402

DB = r"D:\cp77-ro\db\strings.db"
BEAM, MINIMAX, DEEPSEEK = "beam:cloud", "minimax-m3.1-flash:cloud", "deepseek:deepseek-flash"
THINK = {BEAM: "medium", MINIMAX: True, DEEPSEEK: None}
PROMPT_VERSION = 4  # bump when the prompts change materially (v3: slang phrasebook, v4: term base)
PHRASEBOOK = pathlib.Path(r"D:\cp77-ro\glossary\phrasebook.json")
SKIP_CATEGORIES = ("gameplay.npc", "ui.credits", "ui.eula")  # random NPC names, credits, EULA stay English
USER_REJECTED_ENGLISH = {"gonk", "gonks", "preem", "scav", "scavs"}  # the user wants Romanian slang for these

# ---------------------------------------------------------------- domains and order

def domain_of(category):
    if category.startswith("dialogue."):
        return "dialogue"
    if category == "media":
        return "media"
    if category.startswith("story."):
        return "written"
    if category in ("ui.unkeyed",) or category.startswith("gameplay.") and category not in (
            "gameplay.rpg", "gameplay.statuseffects", "gameplay.quickhacks", "gameplay.inputhints",
            "gameplay.scanning", "gameplay.crafting", "gameplay.photomode", "gameplay.devices"):
        return "items"
    return "ui"


def priority_of(category, depot):
    d = domain_of(category)
    p = depot.replace("\\", "/")
    if d == "ui":
        return 0
    if category == "dialogue.quest" and re.search(r"/quest/(q00\d|q10[0-1])/", p):
        return 1  # prologue + first act opening: test in-game early
    if category == "dialogue.quest":
        return 2
    if d == "written":
        return 3
    if d == "items":
        return 4
    if d == "dialogue":
        return 5
    return 6

# ---------------------------------------------------------------- prompts

COMMON = """You translate Cyberpunk 2077 (incl. Phantom Liberty) from English into Romanian for a fan localization.
Quality bar: a professional AAA Romanian localization that a Romanian gamer would praise.

SETTING & LANGUAGE
- Night City, 2077: high-tech, hyper-commercial, English-dominated American megacity. Write Romanian the way young
  urban Romanians talk and write today. NO archaisms, no bookish/folkloric/rural words, no stiff calques.
- Romglish is fine where Romanian gamers/IT people would use it, mainly the glossary's kept terms; inflect them
  with Romanian endings (gig-ul, netrunnerii). EXCEPTION, the user's call: choom/choomba never take Romanian
  endings, only the English forms choom, chooms, choomba, choombas (not choomul/choomii/choom-ul: "choomul meu"
  -> "un choom de-al meu", "choomii mei" -> "chooms de-ai mei"). Do not invent extra English words beyond the glossary
  and common gamer vocabulary.
- Foreign-name inflection: prefer a head noun ("corporația Arasaka", "gașca Maelstrom"); for people use "lui"
  ("lui Judy", "lui Jackie", "lui River", "lui Evelyn"), except female names ending in -a, which take -ei
  ("Fionei", "Reginei").
- Translate idioms by MEANING with the idiom a Romanian would actually say; never word for word. Banned calques:
  "e ca și cum..." (it's like), "e despre..." (it's about), "asta vine de la..." (that's coming from), "îmi pare
  rău să aud" (sorry to hear) -> "păcat"/"îmi pare rău", "pentru acum" (for now) -> "deocamdată", "Mă imaginez" ->
  "Îmi imaginez", "realizez" (realize) -> "îmi dau seama", "Sfinte căcat" -> "Ce căcat", "Suntem terminați" ->
  "S-a zis cu noi". Drop English fillers instead of translating them (trailing "too/there/as well" -> no
  "de asemenea"; "I will" -> "o să").
- Grammar: check imperatives (Aleargă, not Alergă), clitics (îți/ți-, s-o, mă), verb person/tense, "ceea ce"
  after a whole clause. Every line must be correct Romanian you would publish.
- The game addresses the player with "tu" everywhere (UI, system messages, NPCs who are not formal).
  Delamain (the AI chauffeur) and service staff who say "sir/ma'am/miss" use "dumneavoastră" with V.
- Known NPC genders for agreement: female - Judy, Panam, Evelyn, Misty, Bug, Rogue, Songbird/So Mi, Alt, Claire,
  Meredith Stout, Regina, Wakako, Hanako, Lizzy Wizzy, Brigitte; male - Jackie, Johnny, River, Kerry, Takemura,
  Dex, Viktor, Saul, Reed, Kurt Hansen, Mr. Hands, Placide.
- Fixed renderings: stack (noun) -> stack/stack-uri, "stacks up to" -> "se cumulează până la"; "for {x} sec." ->
  "timp de {x} sec."; Cooldown -> timp de recuperare; machine -> aparat/automat ("mașină" = car only); Override ->
  Forțează; Remove (an object) -> Scoate; Loot X -> Ia X; bug (spy device) -> microfon; "the corps" ->
  corporațiile; jack in / slot in -> a se conecta; "Brought to you by" -> "Oferit de"; operatives -> agenți;
  "I feel for X" -> "îmi pare rău de X"/"îl înțeleg pe X" (never "simt ceva pentru"); "good luck" -> "Baftă"/"Mult
  succes"; "fuckin'/fucking" as an intensifier is never softened to "dracu'"/"la naiba" alone.
- Song, album, artist, show and venue titles stay exactly as in the source, whatever language they are in.
- Correct Romanian spelling with ș/ț (comma below), ă, â, î. Romanian capitalization: sentence case, not Title Case
  ("Save Game" -> "Salvează jocul"); keep ALL CAPS where the source is all caps.
- Never output Polish or any language other than Romanian (except names, glossary-kept terms and foreign flavor
  words already in the English line, e.g. hermano, chica, cabrón, gato, arigatou).

GLOSSARY: the GLOSSARY section lists mandatory renderings for terms in this batch (term -> Romanian, notes).
Use them consistently. A term marked as a game mechanic/UI label applies only where the text uses it in that
sense ("Cool" the attribute vs "cool" the adjective).

MUST PRESERVE EXACTLY (copy character for character):
- placeholders like {int_0}, {float_1}, {stat_0}, {player_name}; literal "\\n" sequences; "[db_db]" prefixes;
- markup tags <r1>, <i2>... and </> (stand-ins for game markup): keep every one, same numbers, around the
  matching Romanian words; translate only the human text between them;
- <mothertongue l="..." m="..." b="..." a="..."/>: keep l and m (foreign words) unchanged, translate only the
  English inside b="" and a="".
- <kiroshi l="..." o="..." t="..." b="..." a=""/>: keep l and o (the foreign original) unchanged, translate the
  English inside t="", b="" and a="" (t is what the Kiroshi optics translator shows).
- debug markers like [CUT CANDIDATE], [DELETED] stay as they are.

V'S GENDER - CHECK EVERY LINE: every adjective/participle describing V must agree with the version (female
version feminine: singură, pregătită, străină, drăguță; male version masculine), also when the English has no
gendered word and also when V is the object ("găsește-l singură", "pe ea o așteptam"). Never collapse a
reference to V into a neutral "asta". When an NPC talks TO or ABOUT V, every word for V follows V's gender too
(mercenarul/mercenara, partenerul/partenera, dator/datoare, sigur/sigură, capabil/capabilă) — so such lines
need both versions. V's gender NEVER changes the gender of the person V talks to or about: an NPC keeps their
own gender in both versions (talking to Chang-Hoon, a man: "ai fost urmărit" in both). The player character V
is male or female. Lines with "g": 1 need two versions: "f" for female V,
"m" for male V (whenever V speaks about themself or is addressed, Romanian agreement changes: pregătit/pregătită,
ai fost/ai fost, te-ai rătăcit/te-ai rătăcit... give both even if identical). If an "en_m" text is given, it is the
English for male V; translate it into "m". For other lines return "m" only if Romanian genuinely needs a different
form for male V, else omit "m". Only V's own lines and lines addressed to V depend on V's gender: an NPC speaking
about themself or about someone else never gets an "m". Keep each version internally consistent (the female
version uses feminine forms everywhere it refers to V, the male version masculine).

OUTPUT: JSON {"t": [{"id": <id>, "f": "<Romanian>", "m": "<optional male-V Romanian>"}]} — every input id
exactly once, nothing else."""

STYLE = {
    "dialogue": """STYLE — SPOKEN DIALOGUE (subtitles of voiced lines; lines are in scene order, use them as context)
- Natural spoken Romanian: contractions and colloquial forms (n-am, nu-i, s-o, c-ai, mi-e, las-o), street slang
  matching the character. Keep roughly the source length (subtitles follow the audio).
- Watch false friends and slang traps: "peeps" = oamenii/tipii (never "pești"), "major league" = "de top"/
  "din liga mare", "gig" stays gig, "job" = treabă/job.
- Profanity: same tier as the English - never softened, never exaggerated, never replaced by a polite idiom:
  damn -> naiba/al naibii; shit -> rahat/căcat/la naiba; bullshit -> rahaturi/căcaturi; fuck (exclamation) ->
  Futu-i!/Pula mea!; "fucking X" (modifier) -> "nenorocitul de X", "X-ul dracului", "al dracului de", "ca
  dracu'" - "futu-i" is ONLY a standalone exclamation or with an object, never an adjective/adverb;
  motherfucker -> futu-i mama mă-sii/nenorocitule; cunt -> pizdă; asshole -> bou/nemernic/jegos.
  "Wake the fuck up, Samurai" -> "Trezește-te dracului, Samurai".
- Vulgar or sexual idioms: use a Romanian vulgar expression with the same meaning and force; never translate
  body parts literally ("what crawled up your ass" -> "ce te-a apucat").
- Interjections are translated (nuh-uh -> nici vorbă/nu-nu; puh-lease -> ei, lasă-mă; bastard -> nemernicule);
  keep sarcasm and irony (and their quotation marks) as sarcasm.
- Address: "tu" among street people, friends, enemies; "dumneavoastră"/"dvs." when the English is formal
  (officials, corpo protocol, service staff, "sir/ma'am").
- [Bracketed choice tags] at the start of a line are V's actions: translate them inside the brackets, short,
  imperative 2nd person singular ([Stand] -> [Ridică-te], [Take shard] -> [Ia shard-ul], [Kiss] -> [Sărută-l/o]...).
- Lines tagged [pl_pl] never appear here (kept Polish on purpose).""",
    "media": """STYLE — TV / RADIO / ADS / NEWS: broadcast and advertising Romanian — punchy, slick, ironic where the
English is; news anchors use a neutral news register. Brand and product names stay English, in their original
order. Rebuild puns and wordplay in Romanian instead of translating them literally.""",
    "written": """STYLE — WRITTEN TEXT (journal, quest objectives, messages, shards, emails, notes)
- Quest objectives: short imperative, 2nd person singular ("Find Dex" -> "Găsește-l pe Dex", "Go to the
  Afterlife" -> "Mergi la Afterlife"). Quest/journal descriptions: natural narrative, 2nd person about V.
- Messages/texts/emails keep the sender's voice: informal stays informal (slang, abbreviations), corporate memos
  formal Romanian business register. Keep formatting, line breaks (\\n) and lists.""",
    "ui": """STYLE — USER INTERFACE (menus, settings, buttons, tooltips, perks, stats, input hints)
- Concise and consistent, like a polished Romanian game UI. Buttons/actions: imperative 2nd person singular
  ("Save" -> "Salvează", "Equip" -> "Echipează"); labels/headers: nouns ("Settings" -> "Setări").
- Aim for at most ~130% of the English length (space on screen is limited); abbreviate only in a natural way
  ("sec.", "max.").
- Perk/stat descriptions: precise, idiomatic, never word for word ("Increases damage by {int_0}%" -> "Crește
  daunele cu {int_0}%"; "Landing a Crit Hit has X% chance to..." -> "Fiecare lovitură critică are X% șansă
  să..."). Stats/attributes are lowercase inside sentences (sănătate, stamină, punct de atribut); only named
  perks/effects keep capitals (Sânge rece).
- Perk names: short Romanian idioms that keep the joke; English only for deliberate pop-culture references.
- Keep the English casing of labels and [bracketed] tags exactly ("[Back]" -> "[Înapoi]", not "[ÎNAPOI]").
  Different English labels in the same menu get different Romanian words.
- In-world ads, billboards and screens (device texts): punchy Romanian ad copy, rebuild puns, speak to the
  reader with "tu" consistently; a "we" motto stays "we" ("Servim și protejăm").""",
    "items": """STYLE — ITEMS (weapons, clothing, cyberware, consumables, item descriptions)
- Brand, manufacturer and model names stay English (Militech, Kiroshi, "M-10AF Lexington"); translate the generic
  noun ("Tactical Vest" -> "Vestă tactică", "Duolayer floral hijab" -> "Hijab floral cu două straturi").
- Descriptions are flavor text: witty, punchy, modern Romanian, same tone and jokes as the English; rebuild
  puns instead of translating them literally.""",
}

# ---------------------------------------------------------------- QA

PROTECT = re.compile(r"\{[^}\s]+\}|<Rich [^>]*>|<Input [^>]*>|</>|\\n|\[db_db\]|\b[mlo]=\"[^\"]*\"")
POLISH_CHARS = re.compile("[łŁżŻźŹśŚćĆńŃęĘąĄ]")
POLISH_WORDS = re.compile(r"\b(się|nie|jest|już|czy|proszę|dobrze|który|która|które|kurwa|jebany|jebani|"
                          r"mordo|szefowo|tylko|jakoś|wszystko|dlaczego|teraz|bardzo|przez|żeby|tak jest)\b", re.I)
CEDILLA = str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})


TAG = re.compile(r"<Rich [^>]*>|<Input [^>]*>")


def mask(text):
    """Swap long markup tags for short <rN>/<iN> stand-ins the model keeps reliably."""
    tags = []

    def sub(m):
        tags.append(m.group(0))
        return f"<{'r' if m.group(0).startswith('<Rich') else 'i'}{len(tags)}>"
    return TAG.sub(sub, text), tags


def unmask(text, tags):
    for n, t in enumerate(tags, 1):
        text = text.replace(f"<{'r' if t.startswith('<Rich') else 'i'}{n}>", t)
    return text


def protected(text):
    return collections.Counter(PROTECT.findall(text))


def qa(en, ro, banned):
    """Returns (fixed_ro, level, notes). level: ok | warn | fail."""
    notes, level = [], "ok"
    ro = (ro or "").translate(CEDILLA)
    if r"\n" in en and "\n" not in en and "\n" in ro:
        ro = ro.replace("\r", "").replace("\n", r"\n")  # model decoded the literal \n into a real newline
    if en.strip() and not ro.strip():
        return ro, "fail", ["gol"]
    if protected(en) != protected(ro):
        missing = protected(en) - protected(ro)
        extra = protected(ro) - protected(en)
        notes.append("placeholder/tag diferit: lipsă " + ", ".join(missing) if missing else "")
        if extra:
            notes.append("în plus " + ", ".join(extra))
        level = "fail"
    plain = PROTECT.sub(" ", ro)
    en_words = set(re.findall(r"\w+", en.lower()))
    leaks = [w for w in re.findall(r"\w+", plain) if w.lower() not in en_words
             and (POLISH_CHARS.search(w) or POLISH_WORDS.fullmatch(w))]
    if leaks:
        notes.append("text polonez")
        level = "fail"
    for b in banned:
        if re.search(rf"(?<!\w){re.escape(b)}", plain, re.I):
            notes.append(f"formă interzisă de glosar: {b}")
            level = "fail"
    words = len(en.split())
    if level == "ok" and words >= 4 and ro.strip() == en.strip():
        notes.append("netradus")
        level = "warn"
    return ro, level, [n for n in notes if n]

# ---------------------------------------------------------------- glossary


class Glossary:
    def __init__(self, con):
        self.entries = {}
        self.banned = []
        forms = []
        for term, variants, typ, dec, ro, gen, pl, note, status in con.execute(
                "SELECT term, variants, type, decision, ro, gender, plural, note, status FROM glossary_final"):
            line = f"{term} ({typ}) -> {ro}"
            if pl:
                line += f" (pl. {pl})"
            if note:
                line += f" — {note[:160]}"
            self.entries[term] = line
            for f in [term] + [v for v in (variants or "").split("|") if v]:
                forms.append((f, term))
            if dec == "translate" and "NICIODATĂ" in (note or ""):
                self.banned.append(term)
        self.banned = sorted(set(self.banned) | USER_REJECTED_ENGLISH)
        forms.sort(key=lambda x: -len(x[0]))
        self.lookup = {}
        long_forms, short_forms = [], []
        for f, term in forms:
            self.lookup[f.lower()] = term
            (short_forms if len(f) <= 3 else long_forms).append(re.escape(f))
        self.re_long = re.compile(r"(?<![\w])(" + "|".join(long_forms) + r")(?![\w])", re.I) if long_forms else None
        self.re_short = re.compile(r"(?<![\w])(" + "|".join(short_forms) + r")(?![\w])") if short_forms else None

    def for_text(self, text):
        found = set()
        for rx in (self.re_long, self.re_short):
            if rx:
                for m in rx.finditer(text):
                    t = self.lookup.get(m.group(1).lower())
                    if t:
                        found.add(t)
        return sorted(found)

class Phrasebook:
    """Natural Romanian for English slang/profanity expressions (built from the game's own dialogue)."""

    def __init__(self, path=PHRASEBOOK):
        self.entries = []
        if path.exists():
            for e in json.loads(path.read_text(encoding="utf-8")):
                try:
                    rx = re.compile(e["match"], re.I)
                except (re.error, KeyError):
                    continue
                senses = "; ".join(f"{x.get('when', '')}: " + " / ".join(x.get("ro", [])) for x in e.get("senses", []))
                line = f'"{e["en"]}" -> {senses}'
                if e.get("avoid"):
                    line += " | NEVER: " + ", ".join(e["avoid"])
                self.entries.append((rx, line))

    def for_text(self, text):
        return [line for rx, line in self.entries if rx.search(text)]

    def matches(self, text):
        return any(rx.search(text) for rx, _ in self.entries)


PHRASES = None
TERMS = None


class TermBase:
    """Curated names/terms (people, places, quests, weapons, cyberware, vehicles, perks...): one Romanian form each,
    used identically everywhere. Matching is case-sensitive on whole words."""

    def __init__(self, con):
        self.ro = {}
        self.cat = {}
        for term, ro, cat in con.execute("SELECT term, ro, category FROM termbase WHERE status = 'keep' AND ro <> ''"):
            self.ro[term] = ro
            self.cat[term] = cat
        # the user's corrections from the review page win over the agents' forms
        for term, corr in con.execute("""SELECT ref, correction FROM reviews WHERE kind = 'term'
                                         AND coalesce(reviewer, 'user') = 'user' AND correction <> ''"""):
            if term in self.ro:
                self.ro[term] = corr
        forms = sorted(self.ro, key=len, reverse=True)
        self.rx = re.compile(r"(?<![\w])(" + "|".join(re.escape(f) for f in forms) + r")(?![\w])") if forms else None

    def for_text(self, text):
        return sorted({m.group(1) for m in self.rx.finditer(text)}) if self.rx else []

    def exact(self, text):
        return self.ro.get(text.strip())

    def check(self, en, ro):
        """Terms of the English line whose Romanian form is missing from the translation."""
        low = ro.lower()
        missing = []
        for t in self.for_text(en):
            form = self.ro[t]
            if form == t:  # kept English: must appear as is
                if t.lower() not in low:
                    missing.append(t)
            else:  # translated: Romanian may inflect, so look for the stems of its words
                stems = [w[:max(4, len(w) - 3)].lower() for w in re.findall(r"\w+", form) if len(w) >= 4]
                if stems and not all(st in low for st in stems):
                    missing.append(t)
        return missing


def tbase(con=None):
    global TERMS
    if TERMS is None:
        TERMS = TermBase(con or sqlite3.connect(DB, timeout=60))
    return TERMS


def phrases():
    global PHRASES
    if PHRASES is None:
        PHRASES = Phrasebook()
    return PHRASES

# ---------------------------------------------------------------- units and batches


def build_batches(con, batch_size, only):
    rows = con.execute(f"""SELECT id, kind, depot_path, ord, key, secondary_key, category, en_female, en_male, pl_gendered
        FROM strings WHERE category NOT IN {SKIP_CATEGORIES} AND (en_female <> '' OR en_male <> '')""").fetchall()
    done = set()
    bad_terms = set()
    if REDO_TERMS:
        for sid, ef, rf in con.execute("""SELECT t.string_id, s.en_female, t.ro_female FROM translations t
                                          JOIN strings s ON s.id = t.string_id"""):
            if tbase(con).exact(ef) and rf != tbase(con).exact(ef):
                bad_terms.add(sid)
            elif tbase(con).check(ef, rf):
                bad_terms.add(sid)
        print(f"term base: {len(bad_terms)} translated strings break it -> redo", flush=True)
    for sid, ver, ef in con.execute("""SELECT t.string_id, coalesce(t.prompt_version, 1), s.en_female
                                       FROM translations t JOIN strings s ON s.id = t.string_id"""):
        if ver < REDO_BELOW:
            continue  # made with a prompt older than requested: redo
        if REDO_PHRASES and ver < 3 and phrases().matches(ef):
            continue  # contains slang/profanity the phrasebook now covers: redo
        if REDO_TERMS and sid in bad_terms:
            continue  # breaks the term base: redo
        done.add(sid)
    # lines a reviewer (user or Claude) already decided keep their reviewed text
    done |= {int(r[0]) for r in con.execute("SELECT ref FROM reviews WHERE kind = 'string'")}
    units = {}
    order = []
    for sid, kind, depot, ord_, key, skey, cat, ef, em, plg in rows:
        if ef.startswith("[pl_pl]"):
            continue  # characters who really speak Polish
        dom = domain_of(cat)
        uk = (dom, ef, em)
        u = units.get(uk)
        if u is None:
            if kind == "subtitle":
                group, pos = depot, (ord_,)
            elif skey:
                group, pos = "-".join(skey.split("-")[:5]), (skey,)
            else:
                group, pos = f"unkeyed:{int(key) // 300 if key.isdigit() else key}", (int(key) if key.isdigit() else 0,)
            u = units[uk] = {"domain": dom, "en_f": ef, "en_m": em, "ids": [], "g": False, "file": depot,
                             "group": group, "prio": priority_of(cat, depot), "pos": pos, "ctx": skey or ""}
            order.append(u)
        u["ids"].append(sid)
        u["g"] = u["g"] or bool(plg) or bool(em)
    todo = [u for u in order if not all(i in done for i in u["ids"])]
    for u in todo:  # only these ids get written: identical lines that are already done (or reviewed) stay as they are
        u["write_ids"] = [i for i in u["ids"] if i not in done]
    if REDO_ONLY:  # only re-translate lines that already have a translation (leave new lines to the main run)
        have = {r[0] for r in con.execute("SELECT string_id FROM translations")}
        todo = [u for u in todo if all(i in have for i in u["ids"])]
    if only:
        todo = [u for u in todo if f"p{u['prio']}" in only]
    todo.sort(key=lambda u: (u["prio"], u["group"], u["pos"]))
    batches, cur = [], []
    for u in todo:
        if cur and (len(cur) >= batch_size or cur[-1]["domain"] != u["domain"] or
                    (u["domain"] == "dialogue" and cur[-1]["group"] != u["group"] and len(cur) >= batch_size // 2)):
            batches.append(cur)
            cur = []
        cur.append(u)
    if cur:
        batches.append(cur)
    return batches


def batch_prompt(batch, gloss, notes_by_id=None):
    text = "\n".join(u["en_f"] + " " + u["en_m"] for u in batch)
    gterms = gloss.for_text(text)
    system = COMMON + "\n\n" + STYLE[batch[0]["domain"]]
    if gterms:
        system += "\n\nGLOSSARY (mandatory):\n" + "\n".join("- " + gloss.entries[t] for t in gterms)
    tb = tbase().for_text(text)
    if tb:
        system += ("\n\nTERM BASE — mandatory, identical everywhere (names in English stay exactly as written; "
                   "translated terms keep their words and only take Romanian endings/articles when grammar needs it):\n"
                   + "\n".join(f"- {t} -> {tbase().ro[t]} ({tbase().cat[t]})" for t in tb))
    said = phrases().for_text(text)
    if said:
        system += ("\n\nPHRASEBOOK — how Romanians actually say these expressions (pick the sense that fits the "
                   "scene; same intensity; never the NEVER forms):\n" + "\n".join("- " + x for x in said))
    files, lines = [], []
    for i, u in enumerate(batch):
        item = {"id": i, "en": mask(u["en_f"])[0]}
        if u["en_m"]:
            item["en_m"] = mask(u["en_m"])[0]
        if u["g"]:
            item["g"] = 1
        if u["domain"] != "dialogue" and u["ctx"]:
            item["key"] = u["ctx"][-60:]
        if notes_by_id and i in notes_by_id:
            item["fix"] = notes_by_id[i]
        short = u["file"].split("\\localization\\en-us\\")[-1]
        if not files or files[-1]["file"] != short:
            files.append({"file": short, "lines": []})
        files[-1]["lines"].append(item)
    return system, json.dumps(files if batch[0]["domain"] == "dialogue" else [l for f in files for l in f["lines"]],
                              ensure_ascii=False), gterms

# ---------------------------------------------------------------- run


def main():
    args = sys.argv[1:]
    opt = {args[i][2:]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
    n_beam, n_mm, n_ds = int(opt.get("beam", 3)), int(opt.get("minimax", 0)), int(opt.get("deepseek", 0))
    stage = opt.get("stage", "translate")  # separate progress rows when two runs work side by side
    batch_size = int(opt.get("batch", 25))
    only = set(opt["only"].split(",")) if "only" in opt else None
    global REDO_BELOW, REDO_PHRASES
    REDO_BELOW = 2 if "--redo-version" in args else 0  # --redo-version: redo lines from prompt v1
    REDO_PHRASES = "--redo-phrases" in args
    global REDO_TERMS
    REDO_TERMS = "--redo-terms" in args
    global REDO_ONLY
    REDO_ONLY = "--redo-only" in args

    con = sqlite3.connect(DB, timeout=60)
    cols = [r[1] for r in con.execute("PRAGMA table_info(translations)")]
    for c in ("glossary_terms", "engine_note", "prompt_version"):
        if c not in cols:
            con.execute(f"ALTER TABLE translations ADD COLUMN {c} TEXT")
    con.commit()
    if "--redo-fail" in args:
        n = con.execute("DELETE FROM translations WHERE qa_status = 'fail'").rowcount
        con.commit()
        print(f"re-queued {n} failed strings", flush=True)
    gloss = Glossary(con)
    batches = build_batches(con, batch_size, only)
    if "max-batches" in opt:
        batches = batches[:int(opt["max-batches"])]
    total_units = sum(len(b) for b in batches)
    print(f"{total_units} units in {len(batches)} batches; glossary {len(gloss.entries)} terms", flush=True)

    lock = threading.Lock()
    state = {"done": 0, "inflight": 0, "fail": 0}
    abort = threading.Event()
    work = queue.Queue()
    for b in batches:
        work.put((b, None))  # (batch, QA notes when it is a retry)

    def set_state(note=None):
        note = note or (f"Beam x{n_beam}" + (f" + DeepSeek x{n_ds}" if n_ds else "") + (f" + MiniMax x{n_mm}" if n_mm else "")
                        + f", loturi de {batch_size} · 429 primite: {llm.stats['rate_limited']}")
        c = sqlite3.connect(DB, timeout=60)
        now = time.time()
        c.execute("""INSERT INTO run_state VALUES (?,?,?,?,?,?,?) ON CONFLICT(stage) DO UPDATE SET
                     total=excluded.total, done=excluded.done, inflight=excluded.inflight,
                     updated_at=excluded.updated_at, note=coalesce(excluded.note, run_state.note)""",
                  (stage, total_units, state["done"], state["inflight"], START, now, note))
        c.commit()
        c.close()

    def log(model, n, ok, secs, err=""):
        c = sqlite3.connect(DB, timeout=60)
        c.execute("INSERT INTO llm_log VALUES (?, ?, ?, ?, ?, ?)", (time.time(), "translate:" + model, n, ok, secs, err))
        c.commit()
        c.close()

    def save(batch, results, model, secs, terms):
        rows = []
        retry = {}
        for i, u in enumerate(batch):
            r = results.get(i)
            if not r:
                retry[i] = "lipsea din răspuns"
                continue
            f, lvl_f, n_f = qa(u["en_f"], unmask(r.get("f", "") or "", mask(u["en_f"])[1]), gloss.banned)
            if tbase().exact(u["en_f"]):  # the string IS a term (item name, quest title...): use the curated form
                f, lvl_f, n_f = tbase().exact(u["en_f"]), "ok", []
            elif lvl_f == "ok" and tbase().check(u["en_f"], f):
                lvl_f, n_f = "warn", ["termen inconsecvent: " + ", ".join(tbase().check(u["en_f"], f))]
            m_raw = unmask(r.get("m") or "", mask(u["en_m"] or u["en_f"])[1])
            if u["en_m"] and not m_raw:
                m_raw = f
            m, lvl_m, n_m = qa(u["en_m"] or u["en_f"], m_raw, gloss.banned) if m_raw else ("", "ok", [])
            if m == f:
                m = ""
            level = "fail" if "fail" in (lvl_f, lvl_m) else "warn" if "warn" in (lvl_f, lvl_m) else "ok"
            notes = n_f + [f"(♂) {n}" for n in n_m]
            if level == "fail":
                retry[i] = "; ".join(notes)
            now = time.time()
            for sid in u.get("write_ids", u["ids"]):
                rows.append((sid, f, m, model, secs, level, "; ".join(notes), now, ",".join(terms),
                             PROMPT_VERSION))
        c = sqlite3.connect(DB, timeout=60)
        c.executemany("""INSERT OR REPLACE INTO translations (string_id, ro_female, ro_male, model, batch_secs,
                         qa_status, qa_notes, created_at, glossary_terms, prompt_version)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""", rows)
        c.commit()
        c.close()
        return retry

    def worker(model):
        while not abort.is_set():
            try:
                batch, notes = work.get_nowait()
            except queue.Empty:
                return
            use = model
            if notes is not None:  # retries go to another engine when there is one
                others = [m for m, n in ((BEAM, n_beam), (DEEPSEEK, n_ds), (MINIMAX, n_mm)) if n and m != model]
                use = others[0] if others else model
            with lock:
                state["inflight"] += 1
            set_state()
            t0 = time.time()
            try:
                system, user, terms = batch_prompt(batch, gloss, notes)
                res = llm.chat_json(system, user, think=THINK[use], model=use, timeout=1200)
                secs = time.time() - t0
                results = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
                retry = save(batch, results, use, secs, terms)
                log(use, len(batch), len(batch) - len(retry), secs)
                if retry and notes is None:  # one retry round, with the QA notes
                    sub = [batch[i] for i in sorted(retry)]
                    work.put((sub, {j: retry[i] for j, i in enumerate(sorted(retry))}))
                with lock:
                    state["done"] += len(batch) - (len(retry) if notes is None else 0)
                    state["fail"] += len(retry) if notes is not None else 0
            except RuntimeError as e:  # the model/API failed: keep going, the batch stays untranslated
                log(use, len(batch), 0, time.time() - t0, str(e)[:300])
                print("batch failed:", use, e, flush=True)
            except Exception as e:  # a bug in this script: stop everything instead of paying for wasted calls
                log(use, len(batch), 0, time.time() - t0, f"BUG {type(e).__name__}: {e}"[:300])
                print("ABORT, bug in translate.py:", traceback.format_exc(), flush=True)
                abort.set()
            finally:
                with lock:
                    state["inflight"] -= 1
                set_state()
                print(f"  {state['done']}/{total_units} units  (still failing after retry: {state['fail']}, 429s: {llm.stats['rate_limited']})", flush=True)

    global START
    START = time.time()
    c = sqlite3.connect(DB, timeout=60)
    c.execute("DELETE FROM run_state WHERE stage = ?", (stage,))  # fresh start time for the ETA
    c.commit()
    c.close()
    set_state()
    with cf.ThreadPoolExecutor(n_beam + n_mm + n_ds) as ex:
        futs = ([ex.submit(worker, BEAM) for _ in range(n_beam)] + [ex.submit(worker, MINIMAX) for _ in range(n_mm)]
                + [ex.submit(worker, DEEPSEEK) for _ in range(n_ds)])
        for f in futs:
            f.result()
    set_state("terminat")
    print("done", state, flush=True)


START = 0.0
REDO_BELOW = 0
REDO_PHRASES = False
REDO_TERMS = False
REDO_ONLY = False

if __name__ == "__main__":
    main()
