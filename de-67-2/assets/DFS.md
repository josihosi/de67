# <Feature> DE-67 Functional Specification

Status: Draft
WEC: `.de67/WEC.md`
Source baseline: `<repository | branch | HEAD | relevant dirty state | inspected date>`

## Document authority

This document is the mechanistic product contract derived from the user-owned WEC and inspected
production code. It is not a task-dispatch plan. If this document conflicts with current code about
what code does, re-inspect the code; if it conflicts with the WEC about what the product should do,
the WEC and the user win.

Status markers:

- `[x]` — present in the production path with proportionate evidence.
- `[ ] 🔴 R-...` — missing, wrong, or unproved; the stable red item is implementation work.

## Functional contract

<Describe the user-visible or caller-visible behavior in the vocabulary of WEC.md.>

```text
<trigger> -> <production behavior> -> <observable outcome>
```

## Project language and terminology

<Record the WEC's canonical names, disallowed synonyms, tone, and owner-chosen implementation or
interface languages. Do not let current code silently rename the user's concept.>

## Current code map

| Concern | Files and symbols | Current production behavior | Evidence |
|---|---|---|---|
| `<concern>` | `<path :: symbol>` | `<what happens now>` | `<call site, test, or observation>` |

## Mechanistic requirements

### 1. <Behavior or subsystem>

Mechanism:

- Files and symbols: `<paths, types, functions, methods, fields>`
- Entry point: `<production caller and call path>`
- Parameters: `<name, type, meaning, default or constraint>`
- Inputs: `<facts and their authoritative source>`
- Preconditions: `<required state and invariants>`
- Transition: `<ordered state or action change>`
- Postconditions: `<durable and observable result>`
- Failure behavior: `<safe rejection, retry, or retained state>`
- Persistence/compatibility: `<save, migration, API, concurrency, or platform effects>`

Implementation status:

- [x] <Implemented production behavior and evidence.>
- [ ] 🔴 R-001 — <Missing, wrong, or unproved production behavior.>
  - Code gap: `<path :: symbol and present behavior>`
  - Required mechanism: `<smallest code-grounded change>`
  - Proof: `<outcome test and observable evidence>`

## Competing systems and override direction

| State or action | Readers | Writers / competing owners | Authoritative decision |
|---|---|---|---|
| `<state/action>` | `<paths :: symbols>` | `<paths :: symbols>` | `<owner, precedence, yield/override, transfer and replay rule>` |

<Explain any atomic ownership transfer, one-action override, identity/version check, idempotency,
or shared primitive with separate policy owners.>

## Acceptance and proof

For each red ID, define:

```text
preconditions -> authoritative owner -> transition -> observable outcome -> artifact -> pass/fail
```

| Red ID | Outcome test | Required evidence | False-green controls |
|---|---|---|---|
| `R-001` | `<production route>` | `<named result/artifact>` | `<shortcut or competing-owner result that must fail>` |

## Freeze record

- Status: `<Draft | Frozen | Refrozen>`
- Frozen source baseline: `<commit/tree and relevant state>`
- User-owned choices: `<WEC clauses or confirmed decisions>`
- Evidence-implied refinements: `<none | each uniquely implied clarification or phase-3 expansion,
  its worker evidence, added red IDs, and the first contradicted premise>`

After freeze, automation may only close existing red items after named proof and remove their red
markers; make an evidence-implied nonmaterial clarification; or append a uniquely implied
same-contract mechanism, ownership/proof detail, and necessary new stable red claim after a verified
phase-3 worker finding. Existing claim identities, text, status, accepted work, and acceptance
strength remain fixed. Refreeze immediately. Product intent, project language, permissions,
user-visible behavior, balance, and materially different design choices remain user-owned.
