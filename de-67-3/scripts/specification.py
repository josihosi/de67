#!/usr/bin/env python3
"""Resolve the single functional specification across the DFS-to-FS migration.

The compatibility file is deliberately a small, hash-bound redirect.  It is not
a second editable copy of the specification: consumers must call this module
instead of reading ``DFS.md`` directly once ``FS.md`` exists.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


FS_FILE = "FS.md"
LEGACY_DFS_FILE = "DFS.md"
_POINTER = re.compile(
    r"\A<!-- DE67:FS-COMPAT canonical=FS\.md sha256=(?P<sha>[0-9a-f]{64}) -->\n?\Z"
)
_STATUS = re.compile(
    r"(?ms)^Implementation status:\s*\n.*?(?=^<!-- DE67:DFS-SLICE:END )"
)
_EMPTY_SLICE = re.compile(
    r"(?m)(<!-- DE67:DFS-SLICE:BEGIN[^>]*-->\n)(?=<!-- DE67:DFS-SLICE:END )"
)


class SpecificationError(RuntimeError):
    """The workspace has no unambiguous functional specification."""


@dataclass(frozen=True)
class Specification:
    path: Path
    text: str
    legacy: bool

    @property
    def label(self) -> str:
        return f".de67/{self.path.name}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compatibility_pointer(fs_path: Path) -> str:
    return f"<!-- DE67:FS-COMPAT canonical=FS.md sha256={_sha256(fs_path)} -->\n"


def render_functional_specification(legacy_text: str) -> str:
    """Remove delivery projections while preserving all functional/slice bytes."""
    functional = _STATUS.sub("", legacy_text)
    return _EMPTY_SLICE.sub(
        r"\1<!-- DE67:FS-SLICE-IDENTITY delivery=work-ledger.md -->\n",
        functional,
    )


def resolve(de67_root: Path) -> Specification:
    """Return the canonical FS or a pre-migration DFS, fail-closed on dual content."""
    fs_path = de67_root / FS_FILE
    dfs_path = de67_root / LEGACY_DFS_FILE
    if fs_path.is_file():
        if not dfs_path.is_file():
            raise SpecificationError(
                "FS.md requires the hash-bound DFS.md compatibility pointer"
            )
        pointer = _POINTER.fullmatch(dfs_path.read_text(encoding="utf-8"))
        if pointer is None:
            raise SpecificationError("FS.md and DFS.md are conflicting mutable specifications")
        if pointer.group("sha") != _sha256(fs_path):
            raise SpecificationError("DFS.md compatibility pointer does not match FS.md")
        return Specification(fs_path, fs_path.read_text(encoding="utf-8"), legacy=False)
    if dfs_path.is_file():
        return Specification(dfs_path, dfs_path.read_text(encoding="utf-8"), legacy=True)
    raise SpecificationError("Missing FS.md and legacy DFS.md")


def resolve_path(path: Path) -> Specification:
    """Resolve a legacy CLI path without making an arbitrary file ambiguous."""
    if path.name in (FS_FILE, LEGACY_DFS_FILE):
        return resolve(path.parent)
    if not path.is_file():
        raise SpecificationError(f"Missing functional specification: {path}")
    return Specification(path, path.read_text(encoding="utf-8"), legacy=path.name == LEGACY_DFS_FILE)
