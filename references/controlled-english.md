# Practical controlled-English guideline

## Status and intent

Use these rules as preferred writing defaults for owner questions, software specifications, work
ledgers, test findings, and blocker messages.

This is a writing guideline. It is not a mechanical rewriting system, an automatic validator, or a
mandatory compliance gate. A writer may deviate when the deviation preserves technical meaning,
expresses uncertainty, or follows established project language.

Apply judgment. Do not force a sentence to follow a rule when the result is less precise or less
useful. Do not create or enforce a controlled dictionary. Do not claim formal ASD-STE100
compliance.

This guideline selects only principles that materially improve clarity and auditability. Apply the
[MSW kernel](msw-kernel.md) to writing and evidence requirements. If a proposed requirement can be
deleted without leaving the requested outcome unmet or unproved, delete the requirement.

## 1. Preserve technical identifiers and project terms

Keep technical identifiers exactly as supplied. These identifiers include:

- issue, claim, gap, revision, and test identifiers;
- commit hashes and version strings;
- code symbols, API names, schema fields, and status values;
- file paths, commands, configuration keys, and quoted log text.

Do not correct their spelling, change capitalization, expand them, pluralize them, or convert them
to ordinary prose.

Use one project term for one concept. Do not alternate between `claim`, `task`, `work item`, and
`job` unless the project defines different meanings. If no official term exists, select a short,
concrete term and use it consistently. Explain an uncommon identifier or project term when the
reader first needs it.

Before:

> The worker picked up job R-009 and the agent started the task.

After:

> The database worker started claim R-009.

## 2. Give each sentence one clear meaning

Prefer literal verbs and concrete nouns. Avoid metaphors, casual jargon, and vague phrasal verbs
such as `spin up`, `look into`, `clean up`, `figure out`, and `sort out`. These expressions are
acceptable when they are established project commands or have one precise project meaning.

Write one main claim, decision, observation, or action in each sentence. Avoid:

- contractions;
- `and/or`;
- nested negatives;
- unclear pronouns;
- semicolons;
- long noun clusters;
- unnecessary parenthetical statements.

Repeat the noun when `it`, `they`, or `this` could refer to more than one item. Prefer expressions
such as `this failure`, `this revision`, `this result`, `this test`, and `this requirement`. Do not
use an unsupported `this`.

Check each use of `with`. It can ambiguously describe a condition, an instrument, ownership, or an
association.

Before:

> The coordinator checked the worker with the stale lock and it failed.

After:

> The coordinator checked the worker while the lock was stale. The worker check failed.

## 3. Use active voice and name the actor

Put the responsible actor before the action. The actor can be a person, process, component, or
authoritative data owner.

Before:

> R-009 was assigned and the database was updated.

After:

> The coordinator assigned R-009. The coordinator updated the database.

Use passive voice only when the actor is unknown or not material. State that limitation when it
helps the reader.

> The file was modified, but the responsible process is unknown.

Do not use passive voice to hide missing ownership.

## 4. Keep sentences short without damaging meaning

Use the shortest sentence that preserves one clear meaning. Split a sentence only when each part
remains technically accurate on its own. A longer sentence is acceptable when splitting it changes
scope, creates ambiguity, or separates information that must remain together.

Give each paragraph one topic. Present information in this order when it applies:

1. Context.
2. Action or observation.
3. Result.
4. Consequence.

Use a vertical list for several requirements, alternatives, conditions, or findings.

Before:

> The supervisor, after seeing that the coordinator had stopped responding even though the process
> still existed, restarted it and reset its claim.

After:

> The supervisor detected an unresponsive coordinator process. The supervisor restarted the
> coordinator. The supervisor reset the claim.

## 5. State conditions before actions or results

Put a condition first when the reader must know the condition before interpreting the action.

Before:

> Stop the merge with a failing migration test.

After:

> If the migration test fails, stop the merge.

Use `if` for a possible condition. Use `when` only for an event that is certain, scheduled, or
recurring. State the alternative when it affects behavior.

> If the lock exists, wait. Otherwise, claim the work.

Prefer positive, testable conditions. Avoid `unless` when `if ... not` is clearer. Do not hide a
condition inside `with`, a trailing clause, or a long parenthetical statement.

## 6. Write instructions as explicit actions

Start an instruction with its primary action verb. Write one instruction per sentence unless the
actions must occur together. Number steps when order matters.

Do not place a required action inside a note, explanation, evidence field, or background paragraph.
Use requirement words consistently:

- `must`: required for acceptance;
- `must not`: prohibited;
- `should`: preferred; a justified deviation is permitted;
- `may`: permitted;
- `can`: describes technical capability.

Do not use `should` for a mandatory requirement. Do not use `can` to express permission. An
instruction should have an observable completion condition when the result is not obvious.

Before:

> The system should maybe ensure the ledger gets updated after processing.

After:

> When the work frontier changes, the coordinator must update the active ledger. SQLite keeps the
> detailed transition history.

Ask one owner decision in each question. Give only the context that the owner needs for the
decision. State the blocked consequence when it is relevant.

Before:

> What should we do about retries and errors?

After:

> Should the coordinator retry claim R-009 after exit code 75? The missing rule blocks the restart
> test.

## 7. Control abbreviations locally

Define an abbreviation at first use in each standalone document unless it is an established
project term. Use one expansion and one capitalization. Do not invent an abbreviation for a term
that appears only a few times.

Preserve established forms such as `API`, `CLI`, `SQLite`, and project-specific initialisms. Do not
treat identifiers such as `R-009` as abbreviations.

Prefer complete expressions such as `for example` and `that is`. Use shortened forms such as
`e.g.`, `i.e.`, and `etc.` only when they cannot cause ambiguity.

## 8. Make evidence claims auditable and proportional

Separate observation, interpretation, and conclusion. Use labels when they help:

- Observed;
- Expected;
- Evidence;
- Result;
- Inference;
- Unknown;
- Not tested.

Never write `works`, `fixed`, `verified`, or `all tests pass` without stating the tested scope.
Include the most direct available evidence. Examples include a command and exit code, run
identifier, commit hash, environment, file and line, database row, timestamp, or exact error text.
Preserve important errors exactly.

Include only the evidence necessary to support the statement. Prefer a stable reference over copied
logs. More evidence is not stronger evidence when the additional material does not change the
conclusion. Before requiring an evidence item, apply the MSW deletion test. If deleting the item
leaves the claim honestly proved, do not require the item.

Apply that test separately to each playtest proof obligation. An incidental setup action may rely on
a later authoritative guard only when the same bound causal route makes that guard necessarily
prove the setup's relevant effect and exclude another cause. Missing, stale, contradictory, or
causally incomplete downstream evidence remains non-green. A focused test never replaces an
integrated route that the requested outcome requires.

State what was not tested when that fact changes the meaning of the result.

Before:

> The fix works.

After:

> Result: `pytest tests/test_claim.py -q` returned `24 passed` on commit `abc1234`. Integration tests
> were not run.

Do not present static inspection as runtime proof.

> Code inspection found a timeout branch in `retry.py:88`. Runtime behavior was not tested.

Do not infer causation without supporting evidence.

> After the restart, ledger updates resumed. The available evidence does not identify the cause.

Use calibrated statements for incomplete evidence. Prefer:

- The evidence shows ...
- The result is consistent with ...
- The available evidence suggests ...
- The cause is unknown.
- This test does not cover ...
- No evidence was found for ...

Avoid `clearly`, `obviously`, `definitely`, and `proven` unless the evidence justifies the word.

## 9. Write software specifications as testable statements

A specification identifies the responsible component, required behavior, triggering condition,
observable result, and relevant exceptions. Use exact technical identifiers when they are necessary
to implement or test the requirement. Explain the product meaning before dense implementation
detail.

Avoid subjective requirements such as `quickly`, `cleanly`, `properly`, `robustly`, `intuitively`,
`as needed`, and `where appropriate`. Replace the word with an observable criterion. If no
authoritative criterion exists, state that the criterion remains undecided. Never invent a numeric
limit to make a requirement appear testable.

Before:

> The system must handle failures gracefully.

After:

> If a worker exits unexpectedly, the coordinator must record the exit code and mark the active
> attempt as interrupted.

## 10. Write DE67 work ledgers as current operational state

A DE67 work ledger describes the current work frontier. It states what is done, what remains open,
the latest material result, and the next necessary action. SQLite and referenced artifacts preserve
detailed event history.

Keep the actor, action, object, current state, direct evidence reference, and remaining uncertainty
when they change the next action. Distinguish planned work from completed work. Do not copy full
attempt history into the active ledger. Do not use the ledger as an advertisement or retrospective
guess.

Do not silently replace an earlier evidence claim. Record a correction in the authoritative event
history. Keep the correction in the active ledger only when it changes the current frontier.

Before:

> R-009 database work completed.

After:

> Latest result: the database worker applied migration M-12 for claim R-009. The migration command
> returned exit code 0. Schema behavior was not tested.

## 11. Write test findings with explicit scope

A test finding identifies what was tested, the conditions, the expected result, the observed
result, the evidence, the scope limitation, and the resulting status. Do not include a field when it
does not change the meaning of the finding.

Do not combine independent findings into one sentence. Do not generalize from one test to the
complete system.

Before:

> Recovery is broken.

After:

> The restart test checked whether the coordinator continued claim R-009. The coordinator
> restarted, but the claim did not continue. Evidence: test T-14 recorded the claim as active after
> 62 seconds. Other recovery paths were not tested.

## 12. Write blocker messages as owner decisions

A blocker message contains:

1. The blocked item.
2. The unmet prerequisite.
3. The evidence.
4. The required owner decision or action.

Use the shortest message that contains those necessary parts.

Before:

> Still stuck because the migration stuff is not there.

After:

> Blocked: claim R-009 requires database migration M-12. Evidence: `alembic heads` does not list
> M-12. Owner action: confirm the migration branch.

Do not label ordinary delay or inconvenience as a blocker. Use `blocked` only when work cannot
continue without an external action, decision, dependency, or missing input. Use `waiting` for an
expected event. Use `uncertain` when available evidence is insufficient.

## 13. Permit deliberate deviations

Deviation is acceptable when it:

- preserves an exact technical quotation;
- preserves an established project term;
- prevents a change in technical meaning;
- expresses uncertainty more accurately;
- keeps an inseparable requirement together;
- follows an external interface or required format;
- makes the text more useful to its intended reader.

Do not rewrite code, commands, logs, identifiers, or quoted external text merely to match these
rules. When a meaningful deviation can confuse a reviewer, record the reason briefly.

> Deviation: the original database error is preserved verbatim.

## Artifact profiles

Apply the same rules with different information density. These profiles describe what the reader
needs. They are not word-count gates.

- **Short — owner and OpenClaw messages.** State the blocked item, the immediate reason, and one
  requested decision or action. Omit process history and implementation detail unless the owner
  needs it to decide.
- A WEC preserves the user's language and decisions without implementation detail.
- **Long — DFS.** State the precise product contract, production owner, transitions, failure cases,
  and honest proof route. Include exact code symbols and causal explanations when they prevent an
  implementation mistake.
- **Medium — work ledger.** State the current frontier, latest material result, direct evidence
  reference, remaining uncertainty, and next necessary action. Omit the full event history and
  background already preserved by the DFS or SQLite.
- A test finding contains the smallest evidence that supports its scoped result.

## Final review

Before publishing an artifact, ask the questions that apply:

- Can the reader identify the actor?
- Can the reader identify the action and affected item?
- Are material conditions stated before the action?
- Does the evidence support the exact statement?
- Does the text distinguish observation from inference?
- Does the text state a material scope limitation or unknown?
- Does the reader know the next required action or decision?
- Can any sentence, proof demand, or evidence item be deleted without weakening the outcome or its
  honest proof?

If an answer is no, revise the text or record a deliberate deviation.
