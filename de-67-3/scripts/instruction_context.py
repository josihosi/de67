"""Common guidance injected once per runtime role when its audited source is absent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


CONFIG_RELATIVE_PATH = Path(".de67/state/workspace.json")
FALLBACK_GUIDANCE = (
    "Use known small queries directly. For broad retrieval, use an available bounded "
    "read-only helper; if none is available, retrieve the needed source yourself with "
    "the same bounded question. Return findings, references, contradictions, and "
    "uncertainty rather than transcripts, and do not repeat a prior survey. Capture "
    "complete build and test output and inspect the runner result and relevant "
    "diagnostics. Keep the current handoff current by replacing obsolete tactics and "
    "status with accepted results, remaining constraints, and evidence references. "
    "Preserve exclusive ownership for edits and mutable runtime operations, and close "
    "temporary processes you own when the work ends."
)


def common_guidance(workspace: str | Path) -> str:
    """Return fallback only until an explicitly audited source remains valid.

    Source references are intentionally not prose comparisons: the Phase-2 caller
    records whether the source was effective for the audited roles.
    """

    path = Path(workspace).resolve() / CONFIG_RELATIVE_PATH
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        guidance = config["guidance"]
        source = Path(guidance["source"])
        digest = guidance["sha256"]
        if (
            guidance["effective"] is True
            and source.is_file()
            and hashlib.sha256(source.read_bytes()).hexdigest() == digest
        ):
            return ""
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return FALLBACK_GUIDANCE
