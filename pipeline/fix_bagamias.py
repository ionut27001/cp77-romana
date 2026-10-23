"""Swear interjections pass: where a short "Fuck." / "Fuck me" / "Goddammit" is frustration or resignation, the
Romanian interjection becomes "Băga-mi-aș" (the user's call, 2026-10-23: "Pula mea" / "Futu-i" sound wrong there).

Only the interjection may change; a line is saved only if the rest stays (almost) identical and tags are intact.
Saved as reviews(reviewer='claude', status='fixed'); lines the user reviewed are never touched.
Usage: python -I -X utf8 fix_bagamias.py [--model claude-haiku-5-5] [--dry-run]
"""
import difflib
import json
import pathlib
import re
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm  # noqa: E402
import pack  # noqa: E402
import translate as T  # noqa: E402

args = sys.argv[1:]
MODEL = "anthropic:" + (args[args.index("--model") + 1] if "--model" in args else "claude-haiku-5-5")
DRY = "--dry-run" in args
# "Shit..." stays "Rahat" / "Căcat": only the fuck family and goddammit are candidates
# "fuck it" (= forget it, screw it) stays "dă-o-n pula mea": not a candidate
EN_INTERJ = re.compile(r"(^|[.!?…]\s*|\.\.\.\s*|[-–]\s*)(fuck(in'?|ing)?( me| hell)?|"
                       r"god ?damn(it)?( it)?|dammit|damn it|fuck's sake|for fuck's sake|aw+ fuck)[.!?…]", re.I)
RO_INTERJ = re.compile(r"\b(futu-?i|pula mea|fir-ar|dracu)\b", re.I)

SYSTEM = """You edit swear interjections in a Romanian translation of Cyberpunk 2077 (modern street Romanian, 2077).
For each line decide whether the short exclamation (translating "Fuck." / "Fuck me." / "Goddammit." / "Shit." used
as an interjection) should become "Băga-mi-aș".

Use "Băga-mi-aș" when the speaker is FRUSTRATED, RESIGNED, ANNOYED or fed up with a situation: things went wrong,
they knew it, bad luck, "here we go again", tired sighs, small mishaps.
KEEP the current word when it fits better (when in doubt, KEEP):
- sudden pain, shock, panic, alarm, a scream in combat ("Optics are busted! Fuck!", "The fuck was that?!") -> keep
- anger AT someone, shouting at a person ("Watch where you're going! Fuck!") -> keep
- disbelief or calling bullshit ("Bull-fuckin'-shit") -> keep
- "fuck it" (= forget it, screw it), translated "dă-o-n pula mea" / "dă-o dracului" -> keep
- amazement / positive surprise ("Fuck, that's beautiful") -> keep
- "fuck" that is not a standalone interjection (a verb, "fuck off", "fuck you", "what the fuck") -> keep
- only replace the interjection that translates the standalone Fuck/Goddammit; leave other swear words in the line
  (e.g. a later "pula mea" inside a sentence) untouched
Change ONLY the interjection word(s); keep everything else exactly (punctuation, tags <r1>, {vars}, \\n, case at
sentence start: "Băga-mi-aș" / lowercase "băga-mi-aș" mid-sentence). Never add new words.
Each input line has id, en, "f" (main Romanian) and optionally "m" (male-V variant). Return every id with "f" and
"m" ("m" = "" when the input had none); return the text unchanged when you keep it."""


def main():
    con = sqlite3.connect(pack.DB, timeout=60)
    tr = pack.load_translations(con, verbose=False)
    user_refs = {r[0] for r in con.execute(
        "SELECT ref FROM reviews WHERE kind='string' AND coalesce(reviewer,'user')='user'")}
    rows = {}
    for sid, depot, key, en in con.execute("SELECT id, depot_path, key, en_female FROM strings"):
        t = tr.get((depot, key))
        if not t or str(sid) in user_refs or not EN_INTERJ.search(en or ""):
            continue
        if RO_INTERJ.search(t[0] or "") or RO_INTERJ.search(t[1] or ""):
            rows.setdefault((en, t[0], t[1] or ""), []).append(sid)  # dedupe identical lines
    units = list(rows.items())
    print(f"{sum(len(v) for v in rows.values())} lines ({len(units)} unique) to judge", flush=True)
    changes = []
    for b in range(0, len(units), 30):
        batch = units[b:b + 30]
        masked = [(T.mask(f), T.mask(m)) for (en, f, m), _ in batch]
        lines = [{"id": i, "en": en[:400], "f": mf[0], **({"m": mm[0]} if m else {})}
                 for i, (((en, f, m), _), (mf, mm)) in enumerate(zip(batch, masked))]
        res = llm.chat_json(SYSTEM, json.dumps({"lines": lines}, ensure_ascii=False), think="low", model=MODEL,
                            retries=3, timeout=600, schema=llm.LINES_SCHEMA)
        got = {r.get("id"): r for r in res.get("t", []) if isinstance(r, dict)}
        for i, ((en, f, m), sids) in enumerate(batch):
            r = got.get(i) or {}
            nf = T.unmask(r.get("f") or "", masked[i][0][1]) or f
            nm = T.unmask(r.get("m") or "", masked[i][1][1]) if m else ""
            if (nf, nm) == (f, m):
                continue
            ok = all(T.protected(new) == T.protected(old) and "băga-mi-aș" in new.lower() and
                     difflib.SequenceMatcher(None, old, new).ratio() > 0.8
                     for new, old in ((nf, f), (nm, m)) if old and new != old)
            if ok:
                changes.append((sids, en, f, m, nf, nm))
        print(f"  {min(b + 30, len(units))}/{len(units)} · {len(changes)} changes · "
              f"${llm.cost(MODEL.split(':', 1)[1]):.3f}", flush=True)
    for sids, en, f, m, nf, nm in changes[:25]:
        print(f"\nEN: {en[:120]}\n   {f[:120]}\n-> {nf[:120]}")
    print(f"\n{len(changes)} unique lines would change ({sum(len(c[0]) for c in changes)} with duplicates)")
    if DRY:
        json.dump([[c[0], c[4], c[5]] for c in changes], open(pack.ROOT / "batch" / "bagamias_plan.json", "w",
                  encoding="utf-8"), ensure_ascii=False)
        return
    now = time.time()
    for sids, en, f, m, nf, nm in changes:
        for sid in sids:
            rf, rm = con.execute("SELECT ro_female, ro_male FROM translations WHERE string_id=?", (sid,)).fetchone()
            con.execute("""INSERT OR REPLACE INTO reviews (kind, ref, status, reason, correction, comment, updated_at,
                           snapshot, reviewer) VALUES ('string', ?, 'fixed', 'băga-mi-aș pass', ?, ?, ?, ?, 'claude')""",
                        (str(sid), nf, json.dumps({"m": nm}, ensure_ascii=False), now, f"{rf}|{rm or ''}"))
    con.commit()
    print("saved")


if __name__ == "__main__":
    main()
