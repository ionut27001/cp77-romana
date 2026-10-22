"""Build D:\\cp77-ro\\db\\strings.db from the serialized English (and Polish reference) localization JSON.

Usage: python -I build_db.py
Re-running rebuilds the `strings` table from scratch (translations live in other tables).
"""
import json
import pathlib
import sqlite3

ROOT = pathlib.Path(r"D:\cp77-ro")
SOURCES = ["base", "ep1"]
DB = ROOT / "db" / "strings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS strings (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,      -- base | ep1
    kind          TEXT NOT NULL,      -- onscreen | subtitle
    depot_path    TEXT NOT NULL,      -- en-us depot path of the file the entry lives in
    ord           INTEGER NOT NULL,   -- position of the entry in its file
    key           TEXT NOT NULL,      -- primaryKey (onscreen) or stringId (subtitle)
    secondary_key TEXT,               -- onscreen only
    category      TEXT NOT NULL,      -- coarse bucket used to pick style rules
    en_female     TEXT NOT NULL,      -- default text (femaleVariant is the main slot)
    en_male       TEXT NOT NULL,      -- only filled when it differs
    pl_female     TEXT,
    pl_male       TEXT,
    pl_gendered   INTEGER NOT NULL DEFAULT 0,  -- Polish has a separate male variant
    words         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_strings_cat ON strings(category);
CREATE INDEX IF NOT EXISTS ix_strings_file ON strings(depot_path, ord);
CREATE UNIQUE INDEX IF NOT EXISTS ux_strings_key ON strings(source, kind, depot_path, key);
"""


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    data = d["Data"]["RootChunk"]["root"]["Data"]
    depot = d["Header"]["ArchiveFileName"]
    depot = depot.split("\\raw\\", 1)[-1].split("\\raw_pl\\", 1)[-1]
    depot = depot.split("\\", 1)[1]  # drop the base|ep1 output folder
    return data, depot


def onscreen_category(skey):
    p = skey.split("-") if skey else []
    if not p:
        return "ui.unkeyed"
    if p[0] == "Story" and len(p) > 2:
        return f"story.{p[2]}"  # journal, gameplay, quest, worlds ...
    if p[0] == "Gameplay" and len(p) > 1:
        return f"gameplay.{p[1].lower()}"
    if p[0] == "UI" and len(p) > 1:
        return f"ui.{p[1].lower()}"
    return p[0].lower()


def subtitle_category(depot):
    p = depot.replace("\\", "/").split("/subtitles/", 1)[1].split("/")
    if p[0] == "quest":
        return "dialogue.quest" if p[1] != "vset" else "dialogue.vset"
    if p[0] == "open_world":
        return {"voicesets": "dialogue.barks", "vendors": "dialogue.vendors"}.get(p[1], f"dialogue.{p[1]}")
    if p[0] == "media":
        return "media"
    return f"dialogue.{p[0]}"


def polish_index(src):
    idx = {}
    for f in (ROOT / "json_pl" / src).glob("*.json"):
        data, depot = load(f)
        if data["$type"] not in ("localizationPersistenceSubtitleEntries", "localizationPersistenceOnScreenEntries"):
            continue
        en_depot = depot.replace("\\pl-pl\\", "\\en-us\\")
        for e in data["entries"]:
            k = e.get("primaryKey") or e.get("stringId")
            idx[(en_depot, k)] = (e["femaleVariant"], e["maleVariant"])
    return idx


def main():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS strings")
    con.executescript(SCHEMA)
    rows = []
    for src in SOURCES:
        pl = polish_index(src)
        for f in sorted((ROOT / "json" / src).glob("*.json")):
            data, depot = load(f)
            t = data["$type"]
            if t == "localizationPersistenceSubtitleMap":
                continue
            # onscreens_final is a byte-identical copy of onscreens; keep one and write both at pack time
            if depot.endswith("onscreens_final.json"):
                continue
            onscreen = t == "localizationPersistenceOnScreenEntries"
            for i, e in enumerate(data["entries"]):
                key = e["primaryKey"] if onscreen else e["stringId"]
                skey = e.get("secondaryKey") if onscreen else None
                cat = onscreen_category(skey) if onscreen else subtitle_category(depot)
                pf, pm = pl.get((depot, key), (None, None))
                text = e["femaleVariant"] + " " + e["maleVariant"]
                rows.append((src, "onscreen" if onscreen else "subtitle", depot, i, key, skey, cat,
                             e["femaleVariant"], e["maleVariant"], pf, pm, int(bool(pm)), len(text.split())))
    con.executemany(
        "INSERT INTO strings (source, kind, depot_path, ord, key, secondary_key, category, en_female, en_male,"
        " pl_female, pl_male, pl_gendered, words) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"{len(rows)} strings -> {DB}")


if __name__ == "__main__":
    main()
