"""Live review UI for the Romanian localization: http://localhost:7077

Reads D:\\cp77-ro\\db\\strings.db while the pipeline writes to it; flags/approvals go to the `reviews` table.
Usage: python -I -X utf8 server.py [port]
"""
import json
import pathlib
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = r"D:\cp77-ro\db\strings.db"
HERE = pathlib.Path(__file__).parent
OLLAMA = "http://localhost:11434/api/tags"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    kind TEXT NOT NULL,          -- glossary | string
    ref TEXT NOT NULL,           -- glossary term or strings.id
    status TEXT NOT NULL,        -- ok | flagged | fixed (Claude corrected it: correction = new form)
    reason TEXT, correction TEXT, comment TEXT,
    updated_at REAL NOT NULL,
    snapshot TEXT,               -- the proposal that was reviewed; a changed proposal re-opens the review
    reviewer TEXT DEFAULT 'user',  -- user | claude; the user's decision always wins
    PRIMARY KEY (kind, ref)
);
CREATE TABLE IF NOT EXISTS translations (
    string_id INTEGER PRIMARY KEY REFERENCES strings(id),
    ro_female TEXT NOT NULL, ro_male TEXT NOT NULL DEFAULT '',
    model TEXT, batch_secs REAL, qa_status TEXT, qa_notes TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS glossary_draft (
    term TEXT PRIMARY KEY, source TEXT, freq INTEGER, is_term INTEGER, type TEXT, decision TEXT, ro TEXT,
    gender TEXT, plural TEXT, alt TEXT, confidence TEXT, note TEXT, examples TEXT,
    batch_secs REAL, created_at REAL, model TEXT, dup_of TEXT
);
CREATE TABLE IF NOT EXISTS llm_log (at REAL, stage TEXT, items INTEGER, answered INTEGER, secs REAL, error TEXT);
CREATE TABLE IF NOT EXISTS run_state (stage TEXT PRIMARY KEY, total INTEGER, done INTEGER,
    inflight INTEGER, started_at REAL, updated_at REAL, note TEXT);
"""


def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def one(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


GLOSSARY_SELECT = """
SELECT g.term, g.source, g.freq, g.type, g.decision, g.ro, g.gender, g.plural, g.alt, g.confidence, g.note,
       g.examples, g.batch_secs, g.created_at, g.model, r.status AS review, r.reason, r.correction, r.comment,
       r.reviewer, (SELECT group_concat(v.term, ' · ') FROM glossary_draft v WHERE v.dup_of = g.term) AS variants
FROM glossary_draft g LEFT JOIN reviews r ON r.kind = 'glossary' AND r.ref = g.term AND (r.snapshot IS NULL OR r.snapshot = g.ro)
WHERE (g.is_term = 1 OR (r.reviewer = 'claude' AND r.status = 'fixed')) AND g.dup_of IS NULL"""

STRING_SELECT = """
SELECT s.id, s.source, s.kind, s.depot_path, s.key, s.secondary_key, s.category, s.en_female, s.en_male,
       s.pl_female, s.pl_male, s.pl_gendered, t.ro_female, t.ro_male, t.model, t.batch_secs, t.qa_status,
       t.qa_notes, t.created_at, r.status AS review, r.reason, r.correction, r.comment, r.reviewer
FROM translations t JOIN strings s ON s.id = t.string_id
LEFT JOIN reviews r ON r.kind = 'string' AND r.ref = CAST(s.id AS TEXT)
    AND (r.snapshot IS NULL OR r.snapshot = t.ro_female || '|' || t.ro_male)
WHERE 1"""


def glossary_item(d):
    d["examples"] = json.loads(d["examples"] or "[]")
    return d


def api_stats(con, q):
    now = time.time()
    try:
        urllib.request.urlopen(OLLAMA, timeout=2).read()
        ollama = True
    except OSError:
        ollama = False
    recent = rows(con, "SELECT * FROM llm_log WHERE at > ? ORDER BY at", (now - 600,))
    ok = [r for r in recent if not r["error"]]
    return {
        "now": now,
        "ollama": ollama,
        "glossary": {
            "candidates": one(con, "SELECT count(*) FROM term_candidates WHERE freq >= 5 OR source LIKE 'slang%'"),
            "drafted": one(con, "SELECT count(*) FROM glossary_draft"),
            "terms": one(con, "SELECT count(*) FROM glossary_draft WHERE is_term = 1 AND dup_of IS NULL"),
            "variants": one(con, "SELECT count(*) FROM glossary_draft WHERE dup_of IS NOT NULL"),
            "noise": one(con, "SELECT count(*) FROM glossary_draft WHERE is_term = 0"),
            "by_type": rows(con, "SELECT type, count(*) n FROM glossary_draft WHERE is_term=1 AND dup_of IS NULL GROUP BY type ORDER BY n DESC"),
            "by_conf": rows(con, "SELECT confidence, count(*) n FROM glossary_draft WHERE is_term=1 AND dup_of IS NULL GROUP BY confidence"),
        },
        "strings": {
            "total": one(con, "SELECT count(*) FROM strings"),
            "translated": one(con, "SELECT count(*) FROM translations"),
        },
        "reviews": rows(con, "SELECT kind, status, coalesce(reviewer, 'user') reviewer, count(*) n FROM reviews GROUP BY 1, 2, 3"),
        "runs": rows(con, "SELECT * FROM run_state ORDER BY updated_at DESC"),
        "llm": {
            "batches": one(con, "SELECT count(*) FROM llm_log WHERE error = ''"),
            "failed": one(con, "SELECT count(*) FROM llm_log WHERE error <> ''"),
            "avg_secs": (sum(r["secs"] for r in ok) / len(ok)) if ok else None,
            "items_10m": sum(r["answered"] for r in ok),
            "missing_10m": sum(r["items"] - r["answered"] for r in ok),
            "last_at": one(con, "SELECT max(at) FROM llm_log"),
            "errors": rows(con, "SELECT at, stage, error FROM llm_log WHERE error <> '' ORDER BY at DESC LIMIT 5"),
        },
    }


def where_filters(q, cols):
    sql, args = "", []
    for param, col in cols.items():
        v = q.get(param)
        if v:
            sql += f" AND {col} = ?"
            args.append(v)
    review = q.get("review")
    if review == "none":
        sql += " AND r.status IS NULL"
    elif review == "human":  # what still needs the user: unreviewed, or Claude asked a question
        sql += " AND (r.status IS NULL OR (r.reviewer = 'claude' AND r.status = 'flagged'))"
    elif review == "claude_fixed":
        sql += " AND r.reviewer = 'claude' AND r.status = 'fixed'"
    elif review == "claude_flagged":
        sql += " AND r.reviewer = 'claude' AND r.status = 'flagged'"
    elif review == "user_flagged":
        sql += " AND coalesce(r.reviewer, 'user') = 'user' AND r.status = 'flagged'"
    elif review:
        sql += " AND r.status = ?"
        args.append(review)
    return sql, args


def api_glossary(con, q):
    sql, args = where_filters(q, {"type": "g.type", "conf": "g.confidence", "decision": "g.decision"})
    if q.get("q"):
        sql += " AND (g.term LIKE ? OR g.ro LIKE ?)"
        args += [f"%{q['q']}%"] * 2
    if q.get("since"):
        sql += " AND g.created_at > ?"
        args.append(float(q["since"]))
    order = {"freq": "g.freq DESC", "term": "g.term COLLATE NOCASE",
             "conf": "CASE g.confidence WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, g.freq DESC",
             }.get(q.get("sort"), "g.created_at DESC")
    limit, offset = min(int(q.get("limit", 60)), 500), int(q.get("offset", 0))
    items = rows(con, f"{GLOSSARY_SELECT}{sql} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset])
    total = one(con, f"SELECT count(*) FROM ({GLOSSARY_SELECT}{sql})", args)
    return {"total": total, "items": [glossary_item(d) for d in items]}


def api_strings(con, q):
    sql, args = where_filters(q, {"category": "s.category", "source": "s.source"})
    if q.get("q"):
        sql += " AND (s.en_female LIKE ? OR t.ro_female LIKE ? OR s.depot_path LIKE ?)"
        args += [f"%{q['q']}%"] * 3
    if q.get("since"):
        sql += " AND t.created_at > ?"
        args.append(float(q["since"]))
    limit, offset = min(int(q.get("limit", 60)), 500), int(q.get("offset", 0))
    items = rows(con, f"{STRING_SELECT}{sql} ORDER BY t.created_at DESC LIMIT ? OFFSET ?", args + [limit, offset])
    total = one(con, f"SELECT count(*) FROM ({STRING_SELECT}{sql})", args)
    return {"total": total, "items": items}


def api_context(con, q):
    """Neighbouring lines of the same file, so a translation can be judged in its scene."""
    sid = int(q["id"])
    s = con.execute("SELECT depot_path, ord FROM strings WHERE id = ?", (sid,)).fetchone()
    return {"items": rows(con, """SELECT s.id, s.ord, s.en_female, s.en_male, t.ro_female, t.ro_male
        FROM strings s LEFT JOIN translations t ON t.string_id = s.id
        WHERE s.depot_path = ? AND s.ord BETWEEN ? AND ? ORDER BY s.ord""", (s[0], s[1] - 4, s[1] + 4))}


def api_review(con, body):
    kind, ref = body["kind"], str(body["ref"])
    if body.get("status") == "clear":
        con.execute("DELETE FROM reviews WHERE kind = ? AND ref = ?", (kind, ref))
    else:
        con.execute("""INSERT OR REPLACE INTO reviews (kind, ref, status, reason, correction, comment, updated_at,
                       snapshot, reviewer) VALUES (?,?,?,?,?,?,?,?,'user')""",
                    (kind, ref, body["status"], body.get("reason", ""), body.get("correction", ""),
                     body.get("comment", ""), time.time(), body.get("snapshot")))
    con.commit()
    return {"ok": True}


def api_terms(con, q):
    """The term base: names/terms that must be translated identically everywhere."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'termbase'").fetchone():
        return {"total": 0, "items": [], "categories": []}
    sql, args = " WHERE t.status = 'keep'", []
    if q.get("cat"):
        sql += " AND t.category = ?"
        args.append(q["cat"])
    if q.get("q"):
        sql += " AND (t.term LIKE ? OR t.ro LIKE ?)"
        args += [f"%{q['q']}%"] * 2
    review = q.get("review")
    if review == "none":
        sql += " AND r.status IS NULL"
    elif review:
        sql += " AND r.status = ?"
        args.append(review)
    base = f"""SELECT t.term, t.category, t.refs, t.ro, t.ro_source, t.note, r.status AS review, r.reason,
                      r.correction, r.comment, coalesce(r.reviewer, 'user') AS reviewer
               FROM termbase t LEFT JOIN reviews r ON r.kind = 'term' AND r.ref = t.term{sql}"""
    order = {"term": "t.term COLLATE NOCASE", "cat": "t.category, t.refs DESC"}.get(q.get("sort"), "t.refs DESC")
    limit, offset = min(int(q.get("limit", 60)), 500), int(q.get("offset", 0))
    items = rows(con, f"{base} ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset])
    for it in items:
        it["kind"] = "term"
    return {"total": one(con, f"SELECT count(*) FROM ({base})", args), "items": items,
            "categories": rows(con, "SELECT category, count(*) n FROM termbase WHERE status = 'keep' GROUP BY 1 ORDER BY 2 DESC")}


GET = {"/api/stats": api_stats, "/api/glossary": api_glossary, "/api/strings": api_strings, "/api/terms": api_terms,
       "/api/context": api_context}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        fn = GET.get(u.path)
        if not fn:
            return self.send(404, {"error": "not found"})
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        con = db()
        try:
            self.send(200, fn(con, q))
        except (sqlite3.Error, ValueError, KeyError, TypeError) as e:
            self.send(400, {"error": str(e)})
        finally:
            con.close()

    def do_POST(self):
        if self.path != "/api/review":
            return self.send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        con = db()
        try:
            self.send(200, api_review(con, body))
        except (sqlite3.Error, KeyError) as e:
            self.send(400, {"error": str(e)})
        finally:
            con.close()

    def log_message(self, *a):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7077
    con = db()
    con.execute("PRAGMA journal_mode=WAL")  # lets the UI read while the pipeline writes
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(reviews)")]
    if "snapshot" not in cols:
        con.execute("ALTER TABLE reviews ADD COLUMN snapshot TEXT")
    if "reviewer" not in cols:
        con.execute("ALTER TABLE reviews ADD COLUMN reviewer TEXT DEFAULT 'user'")
        con.execute("UPDATE reviews SET reviewer = 'user'")
    if "dup_of" not in [r[1] for r in con.execute("PRAGMA table_info(glossary_draft)")]:
        con.execute("ALTER TABLE glossary_draft ADD COLUMN dup_of TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS ix_gd_dup ON glossary_draft(dup_of)")  # variants subquery
    con.execute("CREATE INDEX IF NOT EXISTS ix_tr_created ON translations(created_at)")  # live feed
    con.commit()
    con.close()
    print(f"review UI on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
