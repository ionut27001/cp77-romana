"""Checks translation files: valid JSON, nothing missing, and the same tags/placeholders as the English line.

Usage: python tools/check.py [file ...]   (no arguments = every file under translations/)
Exit code 1 if anything is wrong; each problem is printed with its file and key.
"""
import json
import pathlib
import re
import sys

# tags, variables and markup the game needs untouched: {var}, <Rich ...>, <Input ...>, </>, literal \n, kiroshi attrs
PROTECT = re.compile(r"\{[^}\s]+\}|<Rich [^>]*>|<Input [^>]*>|</>|\\n|\[db_db\]|\b[mlo]=\"[^\"]*\"")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def tokens(text):
    return sorted(PROTECT.findall(text or ""))


def check(path):
    problems = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"{path}: invalid JSON ({e})"]
    if not isinstance(doc, dict) or "depot" not in doc or not isinstance(doc.get("entries"), list):
        return [f"{path}: expected {{\"depot\": ..., \"entries\": [...]}}"]
    for e in doc["entries"]:
        key = e.get("key")
        if not isinstance(e.get("en"), str) or not isinstance(e.get("ro"), str):
            problems.append(f"{path} key {key}: \"en\" and \"ro\" must be text")
            continue
        if e["en"].strip() and not e["ro"].strip():
            problems.append(f"{path} key {key}: empty translation")
        if tokens(e["en"]) != tokens(e["ro"]):
            problems.append(f"{path} key {key}: tags/variables differ from English: "
                            f"{tokens(e['en'])} vs {tokens(e['ro'])}")
        if e.get("ro_m") and tokens(e.get("en_m") or e["en"]) != tokens(e["ro_m"]):
            problems.append(f"{path} key {key}: ro_m tags/variables differ from English")
    return problems


def main():
    files = [pathlib.Path(a) for a in sys.argv[1:] if a.endswith(".json")] or \
        sorted((ROOT / "translations").rglob("*.json"))
    problems = [p for f in files if f.exists() for p in check(f)]
    for p in problems:
        print(p)
    print(f"{len(files)} files checked, {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
