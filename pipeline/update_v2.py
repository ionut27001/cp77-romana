"""Bring strings.db up to date with a game update (text extracted into D:\\cp77-ro\\v2 by extract_v2.py).

1. Files the update added come out of WolvenKit as <fnv1a64>.bin (unknown names); their real depot paths are
   recovered from the subtitle map, they are renamed and serialized.
2. Every entry of the new text is compared with strings.db:
   new key -> inserted; changed English -> text updated and its translation dropped (re-translated later);
   keys gone from the game are left alone (they are simply not written by pack.py).
3. pack.py then reads its templates from v2 (see JSON_ROOT there).

Usage: python -I -X utf8 update_v2.py [--dry-run]
"""
import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

V2 = pathlib.Path(r"D:\cp77-ro\v2")
DB = r"D:\cp77-ro\db\strings.db"
WK = [r"D:\cp77-ro\tools\dotnet\dotnet.exe", r"D:\cp77-ro\tools\wolvenkit\WolvenKit.CLI.dll"]
ENV = dict(os.environ, DOTNET_ROOT=r"D:\cp77-ro\tools\dotnet")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build_db import onscreen_category, subtitle_category  # noqa: E402

DEPOT = re.compile(r"(?:^|\\)((?:base|ep1)\\localization\\.*)$", re.I)


def fnv1a64(s):
    h = 0xcbf29ce484222325
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def wk(*args):
    r = subprocess.run(WK + list(args) + ["-v", "Minimal"], env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-1500:] + r.stderr[-1500:])


def subtitle_paths():
    for f in (V2 / "json_en" / "base").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))["Data"]["RootChunk"]["root"]["Data"]
        if d["$type"] == "localizationPersistenceSubtitleMap":
            return {e["subtitleFile"]["DepotPath"]["$value"] for e in d["entries"]}
    return set()


def name_bins():
    """Rename hashed .bin files to their depot paths and serialize them next to the other JSON."""
    paths = subtitle_paths()
    for lang, loc in (("en", "en-us"), ("pl", "pl-pl")):
        for src in ("base", "ep1"):
            raw = V2 / f"raw_{lang}" / src
            bins = {p.stem: p for p in raw.glob("*.bin")}
            if not bins:
                continue
            named = V2 / f"named_{lang}" / src
            for p in paths:
                lp = p.replace("\\en-us\\", f"\\{loc}\\")
                h = str(fnv1a64(lp.lower()))
                if h in bins:
                    dest = named / lp
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bins[h], dest)
            out = V2 / f"json_{lang}" / src
            wk("convert", "serialize", str(named), "-o", str(out))
            print(f"{lang}/{src}: named {sum(1 for _ in named.rglob('*.json'))} new files", flush=True)


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    data = d["Data"]["RootChunk"]["root"]["Data"]
    m = DEPOT.search(d["Header"]["ArchiveFileName"])
    return data, (m.group(1) if m else None)


def entries(lang, src):
    out = {}
    for f in sorted((V2 / f"json_{lang}" / src).glob("*.json")):
        data, depot = load(f)
        if not depot or data["$type"] not in ("localizationPersistenceSubtitleEntries",
                                               "localizationPersistenceOnScreenEntries"):
            continue
        if depot.endswith("onscreens_final.json"):
            continue
        depot = depot.replace("\\pl-pl\\", "\\en-us\\")
        onscreen = data["$type"] == "localizationPersistenceOnScreenEntries"
        for i, e in enumerate(data["entries"]):
            key = e["primaryKey"] if onscreen else e["stringId"]
            out[(src, depot, key)] = (onscreen, i, e)
    return out


def main():
    dry = "--dry-run" in sys.argv
    name_bins()
    con = sqlite3.connect(DB, timeout=60)
    have = {(s, d, k): (i, ef, em) for i, s, d, k, ef, em in con.execute(
        "SELECT id, source, depot_path, key, en_female, en_male FROM strings")}
    new_rows, changed, same = [], [], 0
    for src in ("base", "ep1"):
        en, pl = entries("en", src), entries("pl", src)
        for k, (onscreen, ordn, e) in en.items():
            ef, em = e["femaleVariant"], e["maleVariant"]
            old = have.get(k)
            if old:
                if (old[1], old[2]) != (ef, em):
                    changed.append((old[0], ef, em))
                else:
                    same += 1
                continue
            skey = e.get("secondaryKey") if onscreen else None
            cat = onscreen_category(skey) if onscreen else subtitle_category(k[1])
            p = pl.get(k)
            pf, pm = (p[2]["femaleVariant"], p[2]["maleVariant"]) if p else (None, None)
            new_rows.append((src, "onscreen" if onscreen else "subtitle", k[1], ordn, k[2], skey, cat, ef, em,
                             pf, pm, int(bool(pm)), len((ef + " " + em).split())))
    print(f"unchanged {same}, changed {len(changed)}, new {len(new_rows)}")
    by_cat = {}
    for r in new_rows:
        by_cat[r[6]] = by_cat.get(r[6], 0) + 1
    print("new by category:", sorted(by_cat.items(), key=lambda x: -x[1])[:20])
    print("new words:", sum(r[12] for r in new_rows))
    if dry:
        return
    con.executemany("""INSERT INTO strings (source, kind, depot_path, ord, key, secondary_key, category, en_female,
                       en_male, pl_female, pl_male, pl_gendered, words) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", new_rows)
    for sid, ef, em in changed:
        con.execute("UPDATE strings SET en_female = ?, en_male = ?, words = ? WHERE id = ?",
                    (ef, em, len((ef + " " + em).split()), sid))
        con.execute("DELETE FROM translations WHERE string_id = ?", (sid,))  # stale: re-translate
    con.commit()
    print("database updated")


if __name__ == "__main__":
    main()
