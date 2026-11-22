#!/usr/bin/env python3
"""Refresh the website's optimized artwork from the original bubbulies game art.

This is an occasional, manual step; the normal build only copies the committed
WebP files. It reads the game repository (read-only), rasterizes each source in
a local headless Chrome canvas and encodes WebP there, because the build host
has no Pillow/cwebp. Sources are embedded as data: URLs in a temporary local
page, so no server or network access is involved.

Usage: python3 Tools/prepare_assets.py --game-repo ~/bubbulies [--chrome PATH]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "PublicSite" / "assets"
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# (source in the game repo, output name, width, height, quality, fit)
# Only files that docs/ASSET_INVENTORY.md lists as project-authored originals.
JOBS = (
    ("public/assets/app-icon-1024.png", "icon-512.webp", 512, 512, 0.9, "cover"),
    ("public/assets/app-icon-1024.png", "icon-180.webp", 180, 180, 0.9, "cover"),
    ("public/assets/app-icon-1024.png", "icon-64.webp", 64, 64, 0.92, "cover"),
    ("public/assets/bubble-mascot.svg", "mascot.webp", 420, 420, 0.9, "contain"),
    ("public/assets/cloud-meadows.svg", "world-cloud-meadows.webp", 585, 1266, 0.84, "cover"),
    ("public/assets/candy-skies.svg", "world-candy-skies.webp", 390, 844, 0.82, "cover"),
    ("public/assets/crystal-lagoon.svg", "world-crystal-lagoon.webp", 390, 844, 0.82, "cover"),
    ("public/assets/starlight-valley.svg", "world-starlight-valley.webp", 390, 844, 0.82, "cover"),
    ("public/assets/moonlight-kingdom.svg", "world-moonlight-kingdom.webp", 390, 844, 0.82, "cover"),
)

# Open-source notices for software shipped inside the game (from the game's
# installed, version-pinned packages). Google Mobile Ads / UMP SDKs are covered
# by Google's own terms, linked from the credits page instead.
LICENSES = (
    ("node_modules/phaser/LICENSE.md", "phaser-LICENSE.txt"),
    ("node_modules/@capacitor/core/LICENSE", "capacitor-core-LICENSE.txt"),
    ("node_modules/@capacitor/ios/LICENSE", "capacitor-ios-LICENSE.txt"),
    ("node_modules/@capacitor/app/LICENSE", "capacitor-app-LICENSE.txt"),
    ("node_modules/@capacitor/haptics/LICENSE", "capacitor-haptics-LICENSE.txt"),
    ("node_modules/@capacitor/preferences/LICENSE", "capacitor-preferences-LICENSE.txt"),
    ("node_modules/@capacitor-community/admob/LICENSE", "capacitor-community-admob-LICENSE.txt"),
    # Firebase JavaScript SDK (package license field "Apache-2.0") and the
    # Firebase Apple SDK are both Apache-2.0; the package ships no LICENSE file,
    # so the standard license text is taken from another installed package.
    ("node_modules/detect-libc/LICENSE", "firebase-Apache-2.0-LICENSE.txt"),
)

CONVERTER = """<!doctype html><meta charset="utf-8"><body>%s<pre id="out"></pre><script>
const jobs = %s;
// Runs on window load, which waits for every embedded image, so headless
// Chrome's virtual-time budget covers decoding before the DOM is dumped.
window.addEventListener('load', () => {
  try {
    const results = {};
    jobs.forEach((job, index) => {
      const img = document.getElementById('i' + index);
      const canvas = document.createElement('canvas');
      canvas.width = job.width; canvas.height = job.height;
      const ctx = canvas.getContext('2d');
      ctx.imageSmoothingQuality = 'high';
      const iw = img.naturalWidth || job.width, ih = img.naturalHeight || job.height;
      const scale = job.fit === 'cover' ? Math.max(job.width / iw, job.height / ih) : Math.min(job.width / iw, job.height / ih);
      const w = iw * scale, h = ih * scale;
      ctx.drawImage(img, (job.width - w) / 2, (job.height - h) / 2, w, h);
      results[job.name] = canvas.toDataURL('image/webp', job.quality);
    });
    document.getElementById('out').textContent = JSON.stringify(results);
  } catch (error) { document.getElementById('out').textContent = 'ERROR ' + error; }
});
</script>"""



def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-repo", type=Path, default=Path.home() / "bubbulies")
    parser.add_argument("--chrome", default=DEFAULT_CHROME)
    args = parser.parse_args()
    game = args.game_repo.expanduser().resolve()
    commit = subprocess.run(["git", "-C", str(game), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="bubbulies-art-") as temporary:
        work = Path(temporary)
        jobs = []
        for index, (source, name, width, height, quality, fit) in enumerate(JOBS):
            mime = "image/svg+xml" if source.endswith(".svg") else "image/png"
            inline = f"data:{mime};base64," + base64.b64encode((game / source).read_bytes()).decode("ascii")
            jobs.append({"src": inline, "name": name, "width": width, "height": height, "quality": quality, "fit": fit})
        images = "".join(f'<img id="i{index}" alt="" src="{job.pop("src")}">' for index, job in enumerate(jobs))
        (work / "convert.html").write_text(CONVERTER % (images, json.dumps(jobs)), encoding="utf-8")
        url = (work / "convert.html").as_uri()
        # Headless Chrome occasionally dumps the DOM before the async canvas work
        # finishes; retry a few times rather than accept a partial result.
        for attempt in range(4):
            dom = subprocess.run([args.chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                  f"--user-data-dir={work / f'profile{attempt}'}", "--virtual-time-budget=30000", "--dump-dom", url],
                                 capture_output=True, text=True, timeout=180).stdout
            match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
            if match and match.group(1).startswith("{"):
                break
    if not match or match.group(1).startswith("ERROR") or not match.group(1).strip():
        raise SystemExit("Chrome conversion failed: " + (match.group(1)[:200] if match else dom[:200]))
    results = json.loads(match.group(1).replace("&quot;", '"').replace("&amp;", "&"))
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = []
    for (source, name, width, height, quality, fit) in JOBS:
        data_url = results[name]
        if not data_url.startswith("data:image/webp;base64,"):
            raise SystemExit(f"{name}: browser did not produce WebP")
        target = ASSETS / name
        target.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        records.append({"source": source, "sourceSha256": sha256(game / source), "output": name,
                        "dimensions": [width, height], "bytes": target.stat().st_size, "sha256": sha256(target)})
    provenance = {
        "schemaVersion": 1,
        "purpose": "Lightweight website copies of original bubbulies artwork; the game's source files are unchanged",
        "gameRepository": "bubbulies (private game repository)",
        "gameCommit": commit,
        "provenance": "docs/ASSET_INVENTORY.md lists every source as project-authored original artwork under the MIT asset notice (licenses/bubbulies-artwork-LICENSE.txt)",
        "encoder": "Google Chrome canvas WebP encoder (headless)",
        "fonts": "None bundled; the site uses device fonts, like the game",
        "images": records,
    }
    (ASSETS / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    licenses = ASSETS / "licenses"
    licenses.mkdir(exist_ok=True)
    shutil.copyfile(game / "public/assets/LICENSE.txt", licenses / "bubbulies-artwork-LICENSE.txt")
    for source, name in LICENSES:
        text = (game / source).read_text(encoding="utf-8")
        if name.startswith("firebase-") and "Apache License" not in text[:200]:
            raise SystemExit("Expected the standard Apache-2.0 text for Firebase")
        (licenses / name).write_text(text, encoding="utf-8")
    print(json.dumps({"written": [r["output"] for r in records], "totalBytes": sum(r["bytes"] for r in records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
