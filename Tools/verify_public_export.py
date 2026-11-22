#!/usr/bin/env python3
"""Verify the public website repository locally. Never deploys or contacts any service.

Checks that:
  * only expected public files are present (no game source, keys or private files);
  * every file matches PUBLICATION_MANIFEST.json (sha256 + size);
  * docs/ reproduces byte-for-byte from PublicSite/ with Tools/build_public_site.py;
  * the published configuration keeps the canonical URL and the AdMob app-ads.txt line.

    python3 Tools/verify_public_export.py                     # verify
    python3 Tools/verify_public_export.py --refresh-manifest  # record reviewed changes, then verify
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile

MANIFEST = "PUBLICATION_MANIFEST.json"
ROOT_FILES = {"README.md", "PUBLISH.md", ".gitignore", ".github/workflows/ci.yml"}
TOOLS = {"Tools/build_public_site.py", "Tools/verify_public_export.py", "Tools/test_public_site.py", "Tools/prepare_assets.py"}
SITE_FILES = {"PublicSite/publisher.json", "PublicSite/site.css", "PublicSite/content/en.json", "PublicSite/content/ar.json"}
SOURCE_DIRS = ("PublicSite/assets/", "PublicSite/tests/", "docs/")
FORBIDDEN_PARTS = {"node_modules", "src", "functions", "ios", "android", ".env", "internal", "__MACOSX"}
FORBIDDEN_NAMES = {"GoogleService-Info.plist", "google-services.json", "service-account.json", "credentials.json", ".env"}
FORBIDDEN_SUFFIXES = {".pem", ".p12", ".p8", ".key", ".jks", ".keystore", ".mobileprovision", ".plist", ".ts", ".js", ".mjs", ".swift", ".zip"}
TEXT_SUFFIXES = {".py", ".json", ".md", ".txt", ".html", ".yml", ".css", ".xml", ""}
CANONICAL = "https://bubbulies.github.io"
APP_ADS_LINE = "google.com, pub-7804927976673782, DIRECT, f08c47fec0942fa0"
SECRET_PATTERNS = (
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r'"type"\s*:\s*"service_account"',
    r'"private_key"\s*:\s*"[^"\s]',
    r"AIza[0-9A-Za-z_-]{35}",
    r"ca-app-pub-[0-9]{16}[~/][0-9]{10}",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",
)


class ValidationError(ValueError):
    pass


def allowed(name):
    return name in ROOT_FILES or name in TOOLS or name in SITE_FILES or name.startswith(SOURCE_DIRS)


def inventory(root):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if rel.parts[0] == ".git" or "__pycache__" in rel.parts or path.name == ".DS_Store":
            continue
        if path.is_symlink():
            raise ValidationError("Symlinks are not allowed: " + rel.as_posix())
        if any(part in FORBIDDEN_PARTS for part in rel.parts):
            raise ValidationError("Private/game directory in the public repository: " + rel.as_posix())
        if not path.is_file():
            continue
        name = rel.as_posix()
        if name == MANIFEST:
            continue
        if not allowed(name) or path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValidationError("Unexpected file in the public repository: " + name)
        data = path.read_bytes()
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = data.decode("utf-8")
            for pattern in SECRET_PATTERNS:
                if re.search(pattern, text):
                    raise ValidationError(f"Possible credential or private identifier in {name}")
            if name == ".github/workflows/ci.yml" and re.search(r"\bsecrets\s*\.", text):
                raise ValidationError("The check workflow must not use secrets")
        files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return files


def write_manifest(root):
    files = inventory(root)
    value = {
        "schemaVersion": 1,
        "scope": "bubbulies public website: reviewed source, tools, tests, optimized artwork, license notices and the generated static site",
        "excludes": ["game source code", "Firebase/AdMob configuration and keys", "signing material", "private documents"],
        "files": [{"path": name, **record} for name, record in files.items()],
    }
    (Path(root) / MANIFEST).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_builder(root):
    spec = importlib.util.spec_from_file_location("bubbulies_site_builder", Path(root) / "Tools/build_public_site.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify(root):
    root = Path(root).resolve()
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        raise ValidationError("Missing " + MANIFEST + " (run with --refresh-manifest after review)")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {}
    for entry in manifest.get("files", []):
        name = entry.get("path", "")
        if not name or name.startswith("/") or ".." in Path(name).parts or name in expected or not allowed(name):
            raise ValidationError(f"Unsafe or unexpected manifest path: {name!r}")
        expected[name] = {"sha256": entry.get("sha256"), "bytes": entry.get("bytes")}
    actual = inventory(root)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        added = sorted(set(actual) - set(expected))
        changed = sorted(n for n in actual.keys() & expected.keys() if actual[n] != expected[n])
        raise ValidationError(f"Repository differs from the manifest; missing={missing} added={added} changed={changed}")
    for name in ROOT_FILES | TOOLS | SITE_FILES:
        if name not in actual:
            raise ValidationError("Required file missing: " + name)
    config = json.loads((root / "PublicSite/publisher.json").read_text(encoding="utf-8"))
    if config.get("baseUrl", "").rstrip("/") != CANONICAL:
        raise ValidationError("baseUrl must stay " + CANONICAL)
    if APP_ADS_LINE not in config.get("appAdsTxt", []):
        raise ValidationError("The AdMob app-ads.txt line is missing from publisher.json")
    builder = load_builder(root)
    with tempfile.TemporaryDirectory(prefix="bubbulies-site-verify-") as temporary:
        output = Path(temporary) / "docs"
        report = builder.build_site(output)
        committed = {p.relative_to(root / "docs").as_posix(): p.read_bytes() for p in (root / "docs").rglob("*") if p.is_file()}
        rebuilt = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
        if committed != rebuilt:
            differ = sorted(set(committed) ^ set(rebuilt) | {k for k in committed.keys() & rebuilt.keys() if committed[k] != rebuilt[k]})
            raise ValidationError("docs/ is stale; rebuild with Tools/build_public_site.py. Differences: " + ", ".join(differ[:20]))
    if (root / "docs/app-ads.txt").read_text(encoding="utf-8").splitlines() != config["appAdsTxt"]:
        raise ValidationError("docs/app-ads.txt does not match publisher.json")
    return {"schemaVersion": 1, "files": len(actual), "bytes": sum(v["bytes"] for v in actual.values()),
            "audit": report["audit"], "reproducible": True, "deployed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--refresh-manifest", action="store_true")
    args = parser.parse_args()
    try:
        if args.refresh_manifest:
            write_manifest(args.root)
        result = verify(args.root)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
