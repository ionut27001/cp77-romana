"""Polish pass through the Message Batches API (async, 50% cheaper, no client-side waiting on a busy model).

Same prompt, detector hints and QA as polish.py (Haiku 5.5 as editor, FULL mode, structured JSON output).
The plan (which units went into which request) is saved to D:\\cp77-ro\\batch\\<batch_id>.json, so results
can be applied later even if this process stops; a line is only overwritten if its Romanian text is still the
one that was sent.

Usage:
  python -I -X utf8 polish_batch.py run [--model claude-haiku-5-5] [--size 40]   # submit, wait, apply
  python -I -X utf8 polish_batch.py apply <batch_id>                              # apply an ended batch
"""
import json
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, r"D:\cp77-ro\tools\pylib")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import anthropic  # noqa: E402
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming  # noqa: E402
from anthropic.types.messages.batch_create_params import Request  # noqa: E402

import llm  # noqa: E402
import polish as P  # noqa: E402
import translate as T  # noqa: E402

DB = T.DB
PLANS = pathlib.Path(r"D:\cp77-ro\batch")


def client():
    return anthropic.Anthropic(api_key=llm.anthropic_key(), max_retries=5)


def set_state(total, done, note):
    c = sqlite3.connect(DB, timeout=60)
    now = time.time()
    c.execute("""INSERT INTO run_state VALUES ('polish',?,?,?,?,?,?) ON CONFLICT(stage) DO UPDATE SET
                 total=excluded.total, done=excluded.done, inflight=excluded.inflight,
                 updated_at=excluded.updated_at, note=excluded.note""", (total, done, 1, now, now, note))
    c.commit()
    c.close()


def submit(model, size, max_tokens=16000):
    con = sqlite3.connect(DB, timeout=60)
    P.ensure_tables(con)
    P.FULL = True
    gloss = T.Glossary(con)
    T.tbase(con)
    us = P.units(con)
    bs = P.batches_of(us, size)
    reqs, plan = [], {}
    for n, b in enumerate(bs):
        system, user = P.prompt(b, gloss)
        cid = f"p{n}"
        reqs.append(Request(custom_id=cid, params=MessageCreateParamsNonStreaming(
            model=model, max_tokens=max_tokens, system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": llm.LINES_SCHEMA}})))
        plan[cid] = [{k: u[k] for k in ("ids", "file", "cat", "en_f", "en_m", "g", "ro_f", "ro_m", "domain")}
                     for u in b]
    batch = client().messages.batches.create(requests=reqs)
    PLANS.mkdir(exist_ok=True)
    (PLANS / f"{batch.id}.json").write_text(json.dumps({"model": model, "plan": plan}, ensure_ascii=False),
                                            encoding="utf-8")
    print(f"submitted {batch.id}: {len(reqs)} requests, {len(us)} units", flush=True)
    return batch.id, len(us)


def wait(batch_id, units):
    c = client()
    while True:
        b = c.messages.batches.retrieve(batch_id)
        rc = b.request_counts
        done = rc.succeeded + rc.errored + rc.canceled + rc.expired
        total = done + rc.processing
        set_state(units, int(units * done / max(total, 1)),
                  f"Haiku 5.5 · Batch API · {done}/{total} cereri gata ({rc.errored} erori)")
        print(f"{b.processing_status}: {done}/{total} done, {rc.errored} errored", flush=True)
        if b.processing_status == "ended":
            return
        time.sleep(60)


class _Obj:
    """Attribute access over the JSON of a downloaded results file (same shape as the SDK objects)."""

    def __init__(self, d):
        self.__dict__.update({k: _Obj(v) if isinstance(v, dict) else
                              [_Obj(x) if isinstance(x, dict) else x for x in v] if isinstance(v, list) else v
                              for k, v in d.items()})

    def __getattr__(self, name):
        return None


def results_from(batch_id, path):
    """Results from a local JSONL file (download it with curl when the SDK stream drops on long downloads)."""
    if path:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield _Obj(json.loads(line))
    else:
        # The SDK's long results stream drops on this PC (WinError 10038), so download the JSONL with curl first.
        import subprocess
        out = PLANS / f"{batch_id}.results.jsonl"
        url = client().messages.batches.retrieve(batch_id).results_url
        subprocess.run(["curl", "-sS", "--retry", "5", "--retry-all-errors", "-o", str(out),
                        "-H", f"x-api-key: {llm.anthropic_key()}", "-H", "anthropic-version: 2023-06-01", url],
                       check=True)
        yield from results_from(batch_id, out)


def apply(batch_id, path=None):
    data = json.loads((PLANS / f"{batch_id}.json").read_text(encoding="utf-8"))
    plan, model = data["plan"], data["model"]
    con = sqlite3.connect(DB, timeout=60)
    gloss = T.Glossary(con)
    T.tbase(con)
    tok = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}
    changed = kept = failed = 0
    now = time.time()
    for r in results_from(batch_id, path):
        units = plan.get(r.custom_id) or []
        if r.result.type != "succeeded":
            failed += len(units)
            continue
        msg = r.result.message
        u_ = msg.usage
        tok["input"] += u_.input_tokens or 0
        tok["cache_write"] += u_.cache_creation_input_tokens or 0
        tok["cache_read"] += u_.cache_read_input_tokens or 0
        tok["output"] += u_.output_tokens or 0
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            got = {x.get("id"): x for x in json.loads(text).get("t", []) if isinstance(x, dict)}
        except ValueError:
            failed += len(units)
            continue
        for i, u in enumerate(units):
            fm = P.check(u, got[i], gloss) if i in got else None
            for sid in u["ids"]:
                cur = con.execute("SELECT ro_female, ro_male FROM translations WHERE string_id = ?", (sid,)).fetchone()
                if not cur or (cur[0], cur[1] or "") != (u["ro_f"], u["ro_m"] or ""):
                    continue  # the line changed since it was sent: leave it
                if fm:
                    con.execute("INSERT OR IGNORE INTO polish_backup VALUES (?,?,?,?,?)",
                                (sid, u["ro_f"], u["ro_m"], None, now))
                    con.execute("""UPDATE translations SET ro_female=?, ro_male=?, polished=?, created_at=?
                                   WHERE string_id=?""", (fm[0], fm[1], P.POLISH_VERSION, now, sid))
                else:
                    con.execute("UPDATE translations SET polished=? WHERE string_id=?", (P.POLISH_VERSION, sid))
            changed += bool(fm)
            kept += not fm
    con.commit()
    p = llm.PRICES[model]
    cost = (tok["input"] * p[0] + tok["cache_write"] * p[1] + tok["cache_read"] * p[2] + tok["output"] * p[3]) / 1e6 / 2
    set_state(changed + kept + failed, changed + kept, f"Haiku 5.5 · gata: {changed} rescrise, {kept} lăsate, "
                                                      f"{failed} eșuate · ${cost:.2f}")
    print(f"applied: {changed} rewritten, {kept} kept, {failed} failed; tokens {tok}; cost ${cost:.2f} (batch -50%)")


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = {args[i][2:]: args[i + 1] for i in range(len(args) - 1) if args[i].startswith("--")}
    if args[0] == "run":
        bid, n = submit(opt.get("model", "claude-haiku-5-5"), int(opt.get("size", 40)),
                        int(opt.get("max-tokens", 16000)))
        wait(bid, n)
        apply(bid)
    elif args[0] == "apply":
        apply(args[1], args[2] if len(args) > 2 else None)
