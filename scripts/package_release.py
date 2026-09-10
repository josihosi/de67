#!/usr/bin/env python3
"""Build reproducible core and optional add-on archives from a committed Git tree."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import zipfile


ROOT_FILES = {"SKILL.md", "README.md", "LICENSE", "RELEASE_PROMOTION.md"}
CORE_ROOTS = {"agents", "references", "de-67-1", "de-67-2", "de-67-3",
              "alignment-audit", "release-packaging", "scripts", "tests", "docs"}
ADDONS = {"dashboard": {"dashboard"},
          "discord": {"openclaw_discord", "direct_input", "openclaw_advisory"}}


def package_for(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if (parts[0] in {".github", ".gitignore"}
            or path.startswith("docs/verification/")
            or (path.startswith("docs/alignment-audit-") and path.endswith(".md"))):
        return None  # Historical lab evidence and repository configuration are not installations.
    if any(part in {".git", ".de67", "__pycache__", "node_modules", ".venv"}
           for part in parts) or path.endswith((".pyc", ".sqlite", ".sqlite3", ".log")):
        raise ValueError(f"Runtime/private path cannot ship: {path}")
    if parts[0] == "integrations":
        for package, directories in ADDONS.items():
            if len(parts) > 2 and parts[1] in directories:
                return package
        raise ValueError(f"Unclassified integration: {path}")
    if path in ROOT_FILES or parts[0] in CORE_ROOTS:
        return "core"
    raise ValueError(f"Unclassified package path: {path}")


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def build(root: Path, ref: str, version: str, output: Path) -> dict:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Use a semantic version such as 3.0.0")
    revision = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    epoch = int(git(root, "show", "-s", "--format=%ct", revision))
    stamp = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc).timetuple()[:6]
    files: dict[str, tuple[bytes, int]] = {}
    with tarfile.open(fileobj=io.BytesIO(git(root, "archive", "--format=tar", revision))) as tree:
        for member in tree:
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"Only regular package files are supported: {member.name}")
            stream = tree.extractfile(member)
            assert stream is not None
            files[member.name] = (stream.read(), member.mode)
    packages: dict[str, dict[str, tuple[bytes, int]]] = {name: {} for name in ("core", *ADDONS)}
    for path, value in files.items():
        package = package_for(path)
        if package is None:
            continue
        packages[package][path] = value
        if package != "core" and path.endswith(".md"):
            # Core users can read optional setup instructions without installing executable add-ons.
            packages["core"][path] = value
    for package in ADDONS:
        packages[package]["LICENSE"] = files["LICENSE"]
    output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name, members in packages.items():
        manifest = {
            "package": name, "version": version, "source_commit": revision,
            "requires_core": None if name == "core" else version,
            "files": {path: hashlib.sha256(value[0]).hexdigest()
                      for path, value in sorted(members.items())},
        }
        destination = output / f"de67-{version}-{name}.zip"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            manifest_path = f"package-manifests/{name}.json"
            content = {**members, manifest_path: ((json.dumps(manifest, indent=2) + "\n").encode(), 0o644)}
            for path, (data, mode) in sorted(content.items()):
                info = zipfile.ZipInfo(f"de67/{path}", date_time=stamp)
                info.create_system = 3
                info.external_attr = (0o100000 | (mode & 0o777)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data, compresslevel=9)
        artifacts.append({"name": destination.name, "files": len(members),
                          "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
    (output / "SHA256SUMS").write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in artifacts), encoding="utf-8")
    return {"version": version, "source_commit": revision, "artifacts": artifacts}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Committed source revision; working-tree files are never packaged")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(Path(__file__).resolve().parents[1], args.ref, args.version, args.output), indent=2))
    except (ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release packaging failed: {error}\n")


if __name__ == "__main__":
    main()
