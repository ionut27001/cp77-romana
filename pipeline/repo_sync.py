"""Two-way sync between strings.db and the public GitHub repo (D:\\cp77-ro\\github\\cp77-romana).

export: writes the shipped text (translations + review fixes, diacritics kept) as editable JSON, one file per game
        localization file, mirrored under translations/<base|ep1>/...; big files are split into numbered chunks.
import: reads the repo back; every line whose Romanian differs from the database becomes a review fix
        (reviewer='github', status='fixed'), which pack.py applies. The user's own reviews are never overwritten;
        lines whose tags/placeholders no longer match the English are rejected.

Usage: python -I -X utf8 repo_sync.py export|import [repo_dir]
"""
import json
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pack  # noqa: E402
import translate as T  # noqa: E402

REPO = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pack.ROOT / "github" / "cp77-romana"
CHUNK = 2000  # entries per file: keeps files small enough to edit in the GitHub web editor


def repo_path(depot):
    # base\localization\en-us\subtitles\quest\q000\x.json -> base/subtitles/quest/q000/x
    parts = depot.replace("\\", "/").split("/")
    return "/".join([parts[0]] + parts[3:])[:-len(".json")]


def export():
    con = sqlite3.connect(pack.DB, timeout=60)
    tr = pack.load_translations(con)
    files = {}
    for depot, key, en_f, en_m in con.execute(
            "SELECT depot_path, key, en_female, en_male FROM strings ORDER BY depot_path, ord"):
        t = tr.get((depot, key))
        if not t or not t[0]:
            continue
        e = {"key": key, "en": en_f}
        if en_m and en_m != en_f:
            e["en_m"] = en_m
        e["ro"] = t[0]
        if t[1] and t[1] != t[0]:
            e["ro_m"] = t[1]
        files.setdefault(depot, []).append(e)
    out = REPO / "translations"
    if out.exists():
        for f in out.rglob("*.json"):
            f.unlink()
    n = 0
    for depot, entries in files.items():
        base = repo_path(depot)
        chunks = [entries[i:i + CHUNK] for i in range(0, len(entries), CHUNK)]
        for i, chunk in enumerate(chunks, 1):
            name = f"{base}.json" if len(chunks) == 1 else f"{base}.{i:03d}.json"
            p = out / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"depot": depot, "entries": chunk}, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8", newline="\n")
            n += 1
    print(f"exported {sum(map(len, files.values()))} entries from {len(files)} game files into {n} files")


def import_():
    con = sqlite3.connect(pack.DB, timeout=60)
    tr = pack.load_translations(con, verbose=False)
    ids = {(d, k): (sid, rf, rm) for sid, d, k, rf, rm in con.execute(
        """SELECT s.id, s.depot_path, s.key, t.ro_female, t.ro_male FROM strings s
           JOIN translations t ON t.string_id = s.id""")}
    owners = dict(con.execute("SELECT ref, coalesce(reviewer, 'user') FROM reviews WHERE kind = 'string'"))
    changed, rejected, kept = 0, [], []
    now = time.time()
    for f in sorted((REPO / "translations").rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        depot = doc["depot"]
        for e in doc["entries"]:
            k = (depot, e["key"])
            if k not in ids or k not in tr:
                continue
            ro, ro_m = e.get("ro", ""), e.get("ro_m", "")
            cur_f, cur_m = tr[k]
            if (ro, ro_m or "") == (cur_f, "" if (cur_m or "") == cur_f else cur_m or ""):
                continue
            where = f"{f.relative_to(REPO)} key {e['key']}"
            if not ro.strip() or T.protected(e["en"]) != T.protected(ro) or \
                    (ro_m and T.protected(e.get("en_m") or e["en"]) != T.protected(ro_m)):
                rejected.append(where)
                continue
            sid, rf, rm = ids[k]
            if owners.get(str(sid)) == "user":
                kept.append(where)  # the user's own review wins over repo edits
                continue
            con.execute("""INSERT OR REPLACE INTO reviews (kind, ref, status, reason, correction, comment, updated_at,
                           snapshot, reviewer) VALUES ('string', ?, 'fixed', 'github', ?, ?, ?, ?, 'github')""",
                        (str(sid), ro, json.dumps({"m": ro_m, "src": "github"}, ensure_ascii=False), now,
                         f"{rf}|{rm or ''}"))
            changed += 1
    con.commit()
    print(f"imported {changed} edits; {len(kept)} skipped (your own review wins); {len(rejected)} rejected (tags)")
    for w in rejected[:50]:
        print("  rejected:", w)
    for w in kept[:50]:
        print("  kept yours:", w)


if __name__ == "__main__":
    {"export": export, "import": import_}[sys.argv[1]]()
