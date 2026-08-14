---
name: de67
description: Route Codex work through de67 discussion, code-grounded specification, or delivery. Use when the user says `de67 1`, `de67 2`, or `de67 3`, invokes `$de67`, or asks Codex to install or integrate de67. Route to exactly one phase and never preload sibling phase instructions.
---

# de67 router

This file routes; it does not run a phase.

Match the user's command and read exactly one entrypoint:

- `de67 1`: read `de-67-1/SKILL.md` for the current-chat discussion and WEC.
- `de67 2`: read `de-67-2/SKILL.md` for code inspection and DFS authoring.
- `de67 3`: read `de-67-3/SKILL.md` for implementation, deadlines, and mutation.

Open the exact selected entrypoint directly; do not inventory or read sibling phase folders for
background or completeness. The handoff artifacts are the interface: phase 2 receives `WEC.md`;
phase 3 receives the frozen `DFS.md` and Phase-2-initialized `.de67/` clock state.

If `$de67` is invoked without a phase, ask one structured multiple-choice question listing the
three phases, put the recommended phase first, and route after the answer. Do not infer implementation
consent from a discussion or specification request.

## Install or integrate

When the user supplies the de67 repository and asks Codex to install or integrate it:

1. Require the OpenAI Codex CLI, Git, and Python 3.10 or newer. de67 is Codex-specific.
2. Before enabling method mutation, create or select a user-owned writable Git fork or repository
   for the de67 lab. Install the skill from that checkout so accepted mutations have reviewable
   commits and can be rewound if harmful. Do not mutate a read-only release copy.
3. Preserve the repository as one intact skill folder with all phase folders, scripts, references,
   assets, and agent metadata. The checkout may be named `de67-lab`; the skill identity remains
   `$de67`.
4. Verify that `codex` and `python` resolve in the execution environment. Phase 3's bundled runner
   invokes the local Codex CLI; do not replace it with a machine-specific wrapper.
5. Verify access to GPT-5.6 Sol, Luna, and Terra. Phase 2 proves the useful worker roster. Reserve the
   exact GPT-5.6 Sol `ultra` pairing for phase-3 mutation review.
6. Run the skill validator when available, then run the bundled Python tests before reporting the
   installation complete.
