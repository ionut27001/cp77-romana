"""Build the Romanian mod archive from strings.db translations.

1. For every serialized en-us localization file (D:\\cp77-ro\\json\\<src>), write a copy with Romanian text
   (lines without a usable translation stay English).
2. WolvenKit deserializes them back to CR2W and the files are laid out under their depot paths.
3. WolvenKit packs the tree into an archive -> D:\\cp77-ro\\dist\\ (and optionally into the game's mod folder).

The mod overrides the en-us text: play with the English language selected (English audio, Romanian text).
Usage: python -I -X utf8 pack.py [--install]
"""
import json
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(r"D:\cp77-ro")
DB = ROOT / "db" / "strings.db"
# run through Microsoft's signed dotnet host: Smart App Control may block the unsigned WolvenKit.CLI.exe launcher
WK = [str(ROOT / "tools" / "dotnet" / "dotnet.exe"), str(ROOT / "tools" / "wolvenkit" / "WolvenKit.CLI.dll")]
ENV_DOTNET = str(ROOT / "tools" / "dotnet")
GAME_MOD = pathlib.Path(r"D:\SteamLibrary\steamapps\common\Cyberpunk 2077\archive\pc\mod")
ARCHIVE_NAME = "zz_cp77_romana"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
# templates = the game's CURRENT English text (re-extracted after each game update, see extract_v2/update_v2);
# using stale templates would overwrite new lines the update added
JSON_ROOT = ROOT / "v2" / "json_en"
# The game font lacks ț (comma below) and the user prefers Romanian without diacritics: strip them in the archive
# only (the database keeps them; pass --diacritics to keep them). Other languages' letters (Polish names) stay.
NO_DIACRITICS = str.maketrans("ăâîșțşţĂÂÎȘȚŞŢ", "aaiststAAISTST")
DIACRITICS = False


def wk(*args):
    env = dict(__import__("os").environ, DOTNET_ROOT=ENV_DOTNET)
    r = subprocess.run(WK + list(args) + ["-v", "Minimal"], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"WolvenKit {args[0]} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r.stdout


def depot_of(header):
    m = re.search(r"(?:^|\\)((?:base|ep1)\\localization\\.*)$", header["ArchiveFileName"], re.I)
    return m.group(1)


def load_translations(con, verbose=True):
    """{(depot, key): (ro_female, ro_male)} as shipped: translations that passed QA, then review fixes on top."""
    tr = {}
    for depot, key, kind, rf, rm in con.execute("""
            SELECT s.depot_path, s.key, s.kind, t.ro_female, t.ro_male FROM translations t
            JOIN strings s ON s.id = t.string_id WHERE t.qa_status <> 'fail'"""):
        tr[(depot, key)] = (rf, rm)
    # line fixes: the user's correction wins, then Claude's fix; only while the reviewed text is still current
    fixes = 0
    for depot, key, rf, rm, status, reviewer, corr, comment, snap in con.execute("""
            SELECT s.depot_path, s.key, t.ro_female, t.ro_male, r.status, coalesce(r.reviewer, 'user'), r.correction,
                   r.comment, r.snapshot
            FROM reviews r JOIN strings s ON r.kind = 'string' AND r.ref = CAST(s.id AS TEXT)
            JOIN translations t ON t.string_id = s.id
            WHERE r.correction <> '' ORDER BY r.reviewer = 'user'"""):
        if snap and snap != f"{rf}|{rm or ''}":
            continue  # re-translated since the review
        if reviewer in ("claude", "github") and status != "fixed":
            continue
        try:
            # claude and github fixes carry their own male variant in the comment JSON
            m = json.loads(comment or "{}").get("m", "") if reviewer in ("claude", "github") else rm
        except ValueError:
            m = rm
        tr[(depot, key)] = (corr, m or "")
        fixes += 1
    if verbose:
        print(f"{len(tr)} translated entries ({fixes} with review fixes)")
    return tr


def main():
    install = "--install" in sys.argv
    global DIACRITICS
    DIACRITICS = "--diacritics" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    tr = load_translations(con)

    if BUILD.exists():
        shutil.rmtree(BUILD)
    jdir, cdir, tree = BUILD / "json", BUILD / "cr2w", BUILD / "tree"
    stats = {"files": 0, "entries": 0, "ro": 0}
    depots = {}
    for src in ("base", "ep1"):
        (jdir / src).mkdir(parents=True)
        for f in sorted((JSON_ROOT / src).glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            data = d["Data"]["RootChunk"]["root"]["Data"]
            if data["$type"] not in ("localizationPersistenceOnScreenEntries", "localizationPersistenceSubtitleEntries"):
                continue
            depot = depot_of(d["Header"])
            # onscreens_final.json is an identical copy of onscreens.json: same translations
            lookup_depot = depot.replace("onscreens_final.json", "onscreens.json")
            changed = 0
            for e in data["entries"]:
                key = e.get("primaryKey") or e.get("stringId")
                t = tr.get((lookup_depot, key))
                stats["entries"] += 1
                if not t:
                    continue
                rf, rm = t
                if not DIACRITICS:
                    rf, rm = (rf or "").translate(NO_DIACRITICS), (rm or "").translate(NO_DIACRITICS)
                if e["femaleVariant"] or rf:
                    e["femaleVariant"] = rf
                e["maleVariant"] = rm or ""
                changed += 1
            if not changed:
                continue
            stats["files"] += 1
            stats["ro"] += changed
            out = jdir / src / f.name
            out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            depots[(src, f.name[:-len(".json")])] = depot
    print(f"{stats['files']} files, {stats['ro']}/{stats['entries']} entries in Romanian")

    for src in ("base", "ep1"):
        (cdir / src).mkdir(parents=True)
        wk("convert", "deserialize", str(jdir / src), "-o", str(cdir / src))
        for (s, name), depot in depots.items():
            if s != src:
                continue
            cr2w = cdir / src / name
            if not cr2w.exists():
                raise RuntimeError(f"deserialize produced no {cr2w}")
            dest = tree / ARCHIVE_NAME / depot
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(cr2w), str(dest))

    DIST.mkdir(exist_ok=True)
    wk("pack", str(tree / ARCHIVE_NAME), "-o", str(DIST))
    archive = DIST / f"{ARCHIVE_NAME}.archive"
    print(f"archive: {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    if install:
        GAME_MOD.mkdir(exist_ok=True)
        shutil.copy2(archive, GAME_MOD / archive.name)
        print(f"installed -> {GAME_MOD / archive.name}")


if __name__ == "__main__":
    main()
