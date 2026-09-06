# Clear language for de67 artifacts

These are writing preferences, not a validator, controlled dictionary, or formal language standard.
Preserve technical meaning, the user's voice, and exact identifiers over stylistic uniformity.

- Lead with the outcome or current decision. Explain why a technical detail matters before adding
  detail the reader does not yet need.
- Use concrete nouns, active verbs, and one clear meaning per sentence. Name the actor when ownership
  matters. Keep related reasoning together instead of scattering it across repetitive fields.
- Preserve paths, commands, symbols, IDs, status values, and quoted errors exactly. Use the project's
  established terms; do not silently rename the user's concept.
- Separate observed behavior, inference, proposals, and unknowns. State the scope of tests and proof.
  A helper test, startup screenshot, or process launch proves only the behavior it reaches.
- Give the smallest direct evidence reference that settles the claim. Link or query full artifacts
  when needed; avoid copying them into every message or repeating a claim's history.
- State real conditions and failure behavior. `Must` means required for acceptance, `should` means a
  preference with room for judgment, and `may` grants permission. Do not convert examples or metrics
  into product thresholds.
- Ask the user for decisions they own. Explain the consequence of an unresolved choice. Ordinary
  delay is waiting; an unmet external requirement is a blocker; insufficient evidence is uncertainty.
- Retain text when it changes intent, a decision, honest proof, or the next action. Apply the
  [MSW decision rule](msw-kernel.md) without treating brevity as an excuse to omit necessary reasoning.

For an active ledger, use the compact [ledger profile](controlled-english-ledger.md). For a blocker
or decision request, use the [owner-message profile](controlled-english-message.md). Ordinary idea
exploration may be conversational; it is not a sequence of blocker notices.

A WEC preserves user intent and open choices. A DFS explains the product mechanism, its rationale,
and how to tell whether it works. A work ledger records the current frontier, latest material
result, uncertainty, and continuation; referenced artifacts preserve history. None needs a fixed
word count, a field for every conceivable detail, or mandatory technical prose in owner messages.
