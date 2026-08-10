---
name: de67-lab
description: Compatibility router for the DE-67 lab. Use when the user says `DE-67-1`, `DE-67-2`, or `DE-67-3`, invokes `$de67-lab`, or asks which phase should handle the current work. Route to exactly one phase and never preload the other phase instructions.
---

# DE-67 lab router

This file routes; it does not run a phase.

Match the user's command and read exactly one entrypoint:

- `DE-67-1` or `$de-67-1`: read `de-67-1/SKILL.md` for the current-chat discussion and WEC.
- `DE-67-2` or `$de-67-2`: read `de-67-2/SKILL.md` for code inspection and DFS authoring.
- `DE-67-3` or `$de-67-3`: read `de-67-3/SKILL.md` for implementation, deadlines, and mutation.

Open the exact selected entrypoint directly; do not inventory or read sibling phase folders for
background or completeness. The handoff artifacts are the interface: phase 2 receives `WEC.md`;
phase 3 receives the frozen `DFS.md` and `.de67/` state.

If `$de67-lab` is invoked without a phase, ask one structured multiple-choice question listing the
three phases, put the recommended phase first, and route after the answer. Do not infer implementation
consent from a discussion or specification request.
