"""Extract + serialize the game's current English and Polish text into D:\\cp77-ro\\v2 (after a game update).

Usage: python -I -X utf8 extract_v2.py
"""
import os
import pathlib
import subprocess

GAME = pathlib.Path(r"D:\SteamLibrary\steamapps\common\Cyberpunk 2077\archive\pc")
OUT = pathlib.Path(r"D:\cp77-ro\v2")
WK = [r"D:\cp77-ro\tools\dotnet\dotnet.exe", r"D:\cp77-ro\tools\wolvenkit\WolvenKit.CLI.dll"]
ENV = dict(os.environ, DOTNET_ROOT=r"D:\cp77-ro\tools\dotnet")


def wk(*args):
    r = subprocess.run(WK + list(args) + ["-v", "Minimal"], env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-1500:] + r.stderr[-1500:])


for lang in ("en", "pl"):
    for folder, src in (("content", "base"), ("ep1", "ep1")):
        raw, js = OUT / f"raw_{lang}" / src, OUT / f"json_{lang}" / src
        raw.mkdir(parents=True, exist_ok=True)
        js.mkdir(parents=True, exist_ok=True)
        if not any(raw.rglob("*.json")):
            wk("extract", str(GAME / folder / f"lang_{lang}_text.archive"), "-o", str(raw))
        if not any(js.glob("*.json")):
            wk("convert", "serialize", str(raw), "-o", str(js))
        print(f"{lang}/{src}: {sum(1 for _ in raw.rglob('*.json'))} raw, {sum(1 for _ in js.glob('*.json'))} json",
              flush=True)
