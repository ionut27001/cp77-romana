"""Polish pass: make existing Romanian sound like real spoken/written Romanian (not a re-translation).

The model sees, scene by scene, the English and the current Romanian, and returns ONLY the lines it rewrites;
everything that already sounds native stays untouched. Rules come from six Claude review agents (~1,700 lines
checked, 2026-10-22). Targets: story dialogue, long barks, media, long written texts. Lines a reviewer already
fixed are skipped. Every change passes the same QA as translate.py; the previous text is kept in polish_backup.

Usage:
  python -I -X utf8 polish.py --dry-run 120      # sample -> bench\\blind.json (current vs polished) for a judge
  python -I -X utf8 polish.py [--beam 3] [--batch 50]
"""
import concurrent.futures as cf
import json
import pathlib
import queue
import random
import re
import sqlite3
import sys
import threading
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import translate as T  # noqa: E402

DB = T.DB
POLISH_VERSION = 1

TARGET = """(s.category IN ('dialogue.quest','dialogue.street_stories','dialogue.scenes','dialogue.scene',
              'dialogue.overlays_quest','dialogue.overlay_open_world','dialogue.overlay_media','dialogue.fixers',
              'dialogue.sandbox_activities','dialogue.community','dialogue.minor_activities','media')
             OR (s.category IN ('dialogue.barks','dialogue.vset','dialogue.vendors') AND s.words > 8)
             OR (s.category LIKE 'story.%' AND length(s.en_female) > 150))"""

EDITOR = """You are a native Romanian editor (young, urban, gamer) polishing a finished Romanian translation of
Cyberpunk 2077. Each line has the English original ("en", "en_m" = English for male V) and the current Romanian
("ro" for female V / default, "ro_m" for male V when different). The meaning is almost always right; the problem
is that many lines SOUND TRANSLATED. Rewrite only those lines so a Romanian would really say/write them; keep
every line that already sounds native exactly as it is (return nothing for it).

What sounds translated (fix it):
- English set phrases word for word -> the Romanian equivalent: "A fost aproape" -> "La mustață"; "sunt scurt"
  (I'm short) -> "nu-mi ajung banii"; "No risk, no reward" -> "Cine nu riscă nu câștigă"; "a fi acolo pentru
  cineva" -> "a fi alături de"/"a putea conta pe"; "îți datorez una" -> "îți rămân dator/datoare"; "la punctul
  ăsta" -> "deja/acum"; "ce-ar fi dacă" -> "și dacă"; "în numele a ce" -> "pentru ce"; "binele mai mare" ->
  "binele general"; "Deal?" -> "Bate palma?/S-a făcut?"; "Deal." -> "S-a făcut."; "Trebuie să-ți desenez?" ->
  "Vrei să-ți fac un desen?"; "ronțăie iarba de sub pământ" -> "e la doi metri sub pământ".
- Written register in speech: "va/voi/vei + verb" -> "o să"; "pentru a" -> "ca să"; "acest/acea/aceste" ->
  "ăsta/aia/astea"; "însă" at the end; "desigur", "cu adevărat", "de-a dreptul", "terifiant", "facilități",
  "în privința"; missing contractions (n-am, nu-i, c-ai, mi-e, s-o, las-o). Keep formal register only for
  formal characters (Delamain, Takemura, Arasaka staff, officials, Mr. Hands).
- Translated fillers: "Ei bine" -> "Păi/Mă rog/Ei"; "nu-i așa?" -> "nu?"; "Oh," -> "A,"/drop; "Huh?" ->
  "Hm?/Cum adică?"; "uh/um" -> "ăă"; "din nou" -> "iar"; "omule" (man) -> "frate".
- Stiff structure: noun chains ("cu închiderea ochilor la"), English word order, sentence-initial gerunds,
  "Există…", "e ceva în neregulă?" -> "S-a întâmplat ceva?", "Așteaptă!" -> "Stai!", "are nevoie de" ->
  "îi trebuie"; a person as direct object needs "pe" + clitic ("îl anunț pe Taki", "s-o ajuți pe V").
- Combat/radio/street: shouts as Romanians shout them ("Sunt sub foc" -> "Trag în mine!", "Ofițer sub atac" ->
  "Agent atacat!", "Capetele jos" -> "Jos capul!", "Mănâncă asta" -> "Na, ia de-aici!"); squad orders in the
  plural; reactions are exclamations ("Where you walking?!" -> "Vezi pe unde mergi!"). Radio/TV use Romanian
  broadcast formulas ("Ați ascultat X", "Ne auzim mâine", "Rămâneți cu noi"); ads are punchy Romanian copy.
- Swearing: same strength as the English, phrased like Romanians swear (see PHRASEBOOK); never softened
  ("nobody gives a fuck" -> "pe nimeni nu-l doare-n pulă"), never added where the English has none; "futu-i"
  only as an exclamation or with an object.
- Texts/messages keep the sender's register (slang, sloppiness, typos when the English has them); emails use
  De la/Către/Re.
- V's gender: in "ro" (female V) every word describing V is feminine, in "ro_m" masculine — also when an NPC
  talks to/about V; if the current line needs gender and has only one version, return both "f" and "m". An NPC
  never changes gender with V.
- Fix real errors too (wrong meaning, wrong person, broken grammar, English left in) when you see them.

Some lines carry "check": notes from an automatic detector about that line — fix those issues for sure (a note
may be a false alarm: ignore it only if the line is already natural and correct).

Never change: names and glossary/term base forms, {placeholders}, tags <r1>…</>, <i1>, <kiroshi …>/<mothertongue …>
attributes l/m/o, literal \\n, [db_db]. Keep roughly the same length for subtitles.

OUTPUT: JSON {"t": [{"id": <id>, "f": "<full rewritten line for female V/default>", "m": "<full male-V line,
only if it must differ>"}]} — ONLY the lines you changed (an empty list is fine)."""

# "full" mode: models are biased toward minimal edits when asked to change only bad lines, so ask for the best
# native version of EVERY line instead (identical is allowed when the line is already perfect).
FULL_OUTPUT = """OUTPUT: JSON {"t": [{"id": <id>, "f": "...", "m": "..."}]} with EVERY line: for each one write how a
native Romanian would actually say/write it, starting from the current Romanian. Do not be shy: if a line sounds
even slightly translated (word order, stiff word, written register in speech, English phrase, filler), rewrite
it. Copy it unchanged only if it is already exactly what a Romanian would say. "m" only when the male-V line
must differ."""


# Automatic detectors for what the review agents kept finding; each hit becomes a "check" note on that line, so
# the editor fixes it for sure (the rest of the line/scene is still polished freely).
DETECT = [
    (r"\bEi bine\b", "„Ei bine” sună tradus -> Păi / Mă rog / Ei"),
    (r"\bnu-i așa\?", "„nu-i așa?” -> „nu?”"),
    (r"\b(va|vei|vom|veți|vor)\s+(?!fi\b)[a-zăâîșț]{3,}", "viitor livresc (va/vei/vom/vor + verb) -> „o să”"),
    (r"\bpentru a\b", "„pentru a” -> „ca să”"),
    (r"\bcu adevărat\b", "„cu adevărat” e de obicei calc (really/truly)"),
    (r"\bdesigur\b", "„desigur” e livresc în vorbire -> sigur / normal / evident"),
    (r"\bexistă\b", "„există” e livresc în vorbire -> e / sunt / ai / găsești"),
    (r"\bde asemenea\b", "„de asemenea” e calc (too/also) -> și / la fel / taie-l"),
    (r"\bîn neregulă\b", "„e ceva în neregulă?” -> „s-a întâmplat ceva?”"),
    (r"\bsub (foc|atac)\b", "jargon de luptă calchiat -> „Trag în mine!”, „Agent atacat!”"),
    (r"^Așteaptă!", "„Așteaptă!” -> „Stai!”"),
    (r"\bomule\b", "„omule” (man) -> „frate” / taie-l"),
    (r"^(Oh|Ah),", "interjecție englezească la început"),
    (r"\bla punctul ăsta\b", "„la punctul ăsta” (at this point) -> „deja / acum”"),
    (r"\bpentru acum\b", "„pentru acum” (for now) -> „deocamdată”"),
    (r"\bîți datorez\b", "„îți datorez una” -> „îți rămân dator/datoare”"),
    (r"\b(a fi|să fiu|să fii|e) acolo pentru\b", "„a fi acolo pentru” -> „a fi alături de / a putea conta pe”"),
    (r"\b(acest|această|acești|aceste|acel|acea|acei|acele)\b", "demonstrativ livresc în vorbire -> ăsta/asta/ăla/aia"),
    (r"\b(căci|Iată)\b", "cuvânt livresc în vorbire"),
    (r"\bchoom(?:b?a)?-?(?:ul|ii|i|ilor|ule|e|ului)\b", "choom rămâne englezesc: choom / chooms, fără terminații"),
    (r"\bc[ăa]c[ăa]ri[ei]", "„căcărie” sună de la țară -> căcat / căcaturi"),
    (r"\b(the|and|you|with|that|this|what|just|really)\b", "a rămas un cuvânt englezesc"),
]
DETECT = [(re.compile(rx, re.I), msg) for rx, msg in DETECT]
SWEAR_EN = re.compile(r"\b(fuck\w*|shit\w*|bitch\w*|cunt|asshole|motherfuck\w*|bullshit|goddamn\w*|damn\w*|piss\w*)\b", re.I)
SWEAR_RO = re.compile(r"(pul|futu|fut|dracu|drac|naib|căcat|rahat|pizd|muie|bou|jeg|nenorocit|curv|târf|mă-sii|cur\b|băga)", re.I)
# English that describes the person addressed: Romanian needs gender agreement there
TO_V = re.compile(r"\byou(?:'re| are| were| look| seem| sound| feel)\s+(?!gonna|going|not\b|the\b|a\b|an\b|in\b|on\b|at\b)\w+"
                  r"|\byourself\b|\byou(?:'ll| will) be (?:alone|fine|safe)\b", re.I)


def hints(u):
    """Detector notes for one line (Romanian text in u['ro_f'] / u['ro_m'])."""
    out = []
    ro = (u["ro_f"] or "") + " " + (u["ro_m"] or "")
    speech = u["domain"] in ("dialogue", "media")
    for rx, msg in DETECT:
        if rx.search(ro) and (speech or "livresc" not in msg):
            out.append(msg)
    en = u["en_f"] + " " + u["en_m"]
    if SWEAR_EN.search(en) and not SWEAR_RO.search(ro):
        out.append("înjurătura din engleză lipsește sau e îndulcită -> păstreaz-o la aceeași intensitate")
    if speech and (u["g"] or TO_V.search(en)) and not u["ro_m"]:
        out.append("dacă replica descrie sau i se adresează lui V și româna cere gen, dă și varianta masculină (m)")
    if "delamain" in u["file"].lower():
        out.append("scenă cu Delamain: Delamain vorbește formal (dumneavoastră)")
    return sorted(set(out))


def ensure_tables(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(translations)")]
    if "polished" not in cols:
        con.execute("ALTER TABLE translations ADD COLUMN polished INTEGER DEFAULT 0")
    con.execute("""CREATE TABLE IF NOT EXISTS polish_backup (string_id INTEGER PRIMARY KEY, ro_female TEXT,
                   ro_male TEXT, model TEXT, polished_at REAL)""")
    con.commit()


def units(con, limit_scenes=None):
    rows = con.execute(f"""SELECT s.id, s.depot_path, s.ord, s.category, s.en_female, s.en_male, s.pl_gendered,
                                  t.ro_female, t.ro_male
        FROM strings s JOIN translations t ON t.string_id = s.id
        WHERE {TARGET} AND coalesce(t.polished, 0) < {POLISH_VERSION} AND t.qa_status <> 'fail'
          AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.kind = 'string' AND r.ref = CAST(s.id AS TEXT))
        ORDER BY s.depot_path, s.ord""").fetchall()
    out, seen = [], {}
    for sid, depot, ord_, cat, ef, em, plg, rf, rm in rows:
        k = (ef, em, rf, rm)
        if k in seen:
            seen[k]["ids"].append(sid)
            continue
        u = {"ids": [sid], "file": depot, "cat": cat, "en_f": ef, "en_m": em, "g": bool(plg or em),
             "ro_f": rf, "ro_m": rm, "domain": T.domain_of(cat)}
        seen[k] = u
        out.append(u)
    return out


def batches_of(us, size):
    bs, cur = [], []
    for u in us:
        if cur and (len(cur) >= size or (cur[-1]["file"] != u["file"] and len(cur) >= size // 2)):
            bs.append(cur)
            cur = []
        cur.append(u)
    if cur:
        bs.append(cur)
    return bs


def prompt(batch, gloss):
    text = "\n".join(u["en_f"] + " " + u["en_m"] for u in batch)
    system = EDITOR if not FULL else EDITOR.rsplit("OUTPUT:", 1)[0] + FULL_OUTPUT
    g = gloss.for_text(text)
    if g:
        system += "\n\nGLOSSARY:\n" + "\n".join("- " + gloss.entries[t] for t in g)
    tb = T.tbase().for_text(text)
    if tb:
        system += "\n\nTERM BASE (never change these forms):\n" + "\n".join(
            f"- {t} -> {T.tbase().ro[t]}" for t in tb)
    ph = T.phrases().for_text(text)
    if ph:
        system += "\n\nPHRASEBOOK:\n" + "\n".join("- " + x for x in ph)
    files = []
    for i, u in enumerate(batch):
        item = {"id": i, "en": T.mask(u["en_f"])[0], "ro": T.mask(u["ro_f"])[0]}
        if u["en_m"]:
            item["en_m"] = T.mask(u["en_m"])[0]
        if u["ro_m"]:
            item["ro_m"] = T.mask(u["ro_m"])[0]
        if u["g"]:
            item["v_gender_matters"] = 1
        h = hints(u)
        if h:
            item["check"] = h
        short = u["file"].split("\\en-us\\")[-1]
        if not files or files[-1]["file"] != short:
            files.append({"file": short, "lines": []})
        files[-1]["lines"].append(item)
    return system, json.dumps(files, ensure_ascii=False)


def check(u, r, gloss):
    """QA a rewrite; returns (f, m) or None to keep the current text."""
    f = T.unmask(r.get("f") or "", T.mask(u["en_f"])[1])
    m_raw = T.unmask(r.get("m") or "", T.mask(u["en_m"] or u["en_f"])[1])
    if u["en_f"].strip():
        f, lvl, _ = T.qa(u["en_f"], f, gloss.banned)
        if lvl == "fail" or T.tbase().check(u["en_f"], f):
            return None
    else:
        f = ""
    m = ""
    if m_raw:
        m, lvl, _ = T.qa(u["en_m"] or u["en_f"], m_raw, gloss.banned)
        if lvl == "fail":
            return None
    elif u["ro_m"] and not r.get("m"):
        m = u["ro_m"]  # the editor left the male version alone
    if m == f:
        m = ""
    if f == u["ro_f"] and m == (u["ro_m"] or ""):
        return None
    return f, m


def main():
    args = sys.argv[1:]
    opt = {args[i][2:]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
    n_beam = int(opt.get("workers", opt.get("beam", 3)))
    global MODEL, EFFORT
    MODEL = opt.get("model", T.BEAM)
    EFFORT = opt.get("effort", "medium")
    claude = MODEL.startswith("anthropic:")
    size = int(opt.get("batch", 50))
    dry = int(opt["dry-run"]) if "dry-run" in opt else 0
    global FULL
    FULL = "--full" in args
    con = sqlite3.connect(DB, timeout=60)
    ensure_tables(con)
    gloss = T.Glossary(con)
    T.tbase(con)
    us = units(con)
    if dry:  # one random run of consecutive lines from a few scenes
        random.seed(7)
        start = random.randrange(0, max(1, len(us) - dry))
        us = us[start:start + dry]
    bs = batches_of(us, size)
    print(f"{len(us)} units in {len(bs)} batches", flush=True)

    lock, abort = threading.Lock(), threading.Event()
    state = {"done": 0, "changed": 0, "inflight": 0}
    work = queue.Queue()
    for b in bs:
        work.put(b)
    results = {}

    def set_state():
        c = sqlite3.connect(DB, timeout=60)
        now = time.time()
        c.execute("""INSERT INTO run_state VALUES ('polish',?,?,?,?,?,?) ON CONFLICT(stage) DO UPDATE SET
                     total=excluded.total, done=excluded.done, inflight=excluded.inflight, updated_at=excluded.updated_at,
                     note=excluded.note""",
                  (len(us), state["done"], state["inflight"], START, now,
                   f"{MODEL.split(':')[-1]} x{n_beam} · {state['changed']} rescrise din {state['done']}"
                   + (f" · ${llm.cost(MODEL.split(':', 1)[1]):.2f}" if claude else "")))
        c.commit()
        c.close()

    def worker():
        while not abort.is_set():
            try:
                b = work.get_nowait()
            except queue.Empty:
                return
            with lock:
                state["inflight"] += 1
            t0 = time.time()
            try:
                system, user = prompt(b, gloss)
                res = llm.chat_json(system, user, think=EFFORT, model=MODEL, timeout=1200,
                                    schema=llm.LINES_SCHEMA if claude and FULL else None)
                got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
                changes = {}
                for i, u in enumerate(b):
                    if i in got:
                        fm = check(u, got[i], gloss)
                        if fm:
                            changes[i] = fm
                if dry:
                    with lock:
                        for i, u in enumerate(b):
                            results[id(u)] = (u, changes.get(i))
                else:
                    c = sqlite3.connect(DB, timeout=60)
                    now = time.time()
                    for i, u in enumerate(b):
                        for sid in u["ids"]:
                            if i in changes:
                                c.execute("INSERT OR IGNORE INTO polish_backup VALUES (?,?,?,?,?)",
                                          (sid, u["ro_f"], u["ro_m"], None, now))
                                c.execute("""UPDATE translations SET ro_female=?, ro_male=?, polished=?, created_at=?
                                             WHERE string_id=?""", (changes[i][0], changes[i][1], POLISH_VERSION, now, sid))
                            else:
                                c.execute("UPDATE translations SET polished=? WHERE string_id=?", (POLISH_VERSION, sid))
                    c.commit()
                    c.close()
                with lock:
                    state["done"] += len(b)
                    state["changed"] += len(changes)
                c = sqlite3.connect(DB, timeout=60)
                c.execute("INSERT INTO llm_log VALUES (?, ?, ?, ?, ?, '')",
                          (time.time(), "polish:" + MODEL.split(":")[-1], len(b), len(changes), time.time() - t0))
                c.commit()
                c.close()
            except RuntimeError as e:
                print("batch failed:", e, flush=True)
            except Exception:
                print("ABORT, bug in polish.py:", traceback.format_exc(), flush=True)
                abort.set()
            finally:
                with lock:
                    state["inflight"] -= 1
                set_state()
                print(f"  {state['done']}/{len(us)} units, rewritten {state['changed']}", flush=True)

    global START
    START = time.time()
    with cf.ThreadPoolExecutor(n_beam) as ex:
        for f in [ex.submit(worker) for _ in range(n_beam)]:
            f.result()

    if dry:
        out = pathlib.Path(r"D:\cp77-ro\bench")
        lines, key = [], {}
        swap = random.Random(11).random() < 0.5
        cur, pol = ("A", "B") if not swap else ("B", "A")
        key = {cur: "current", pol: "polished"}
        for n, (u, ch) in enumerate(results.values()):
            new = ch or (u["ro_f"], u["ro_m"])
            lines.append({"id": n, "file": u["file"].split("\\en-us\\")[-1], "en": u["en_f"], "en_m": u["en_m"],
                          "v_gendered": u["g"],
                          "versions": {cur: {"f": u["ro_f"], "m": u["ro_m"]}, pol: {"f": new[0], "m": new[1]}}})
        (out / "blind.json").write_text(json.dumps({"lines": lines}, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "key.json").write_text(json.dumps(key), encoding="utf-8")
        print(f"dry run: {state['changed']}/{len(lines)} lines rewritten -> bench\\blind.json", flush=True)


START = 0.0
FULL = False
MODEL = "beam:cloud"
EFFORT = "medium"

if __name__ == "__main__":
    main()
