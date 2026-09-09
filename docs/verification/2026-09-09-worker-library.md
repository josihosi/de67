# Named-worker simulation evidence

Observed 2026-09-09. These are real Sol/Luna coordination runs over dated CAOL evidence excerpts in isolated disposable workspaces. No game was run, no production coordinator was started or restarted, and this is not gameplay, product-repair, or mutation-review proof.

## Baseline: sound interpretation, related reuse, independent NPC charter

Workspace: `/Volumes/CodexBulk/Schanigarten/workspaces/de67-worker-library-sim-20260909-final`.
Raw observation report: `protocol/observations.json`; complete final accounting: `protocol/night-footing-after.json`. Candidate hashes are retained per attempted stage in the observation report. Two of four requested stages completed; the third stopped at a real unresolved deadline-review gate. The fourth was not attempted.

| Role / task | Actual model session UUID |
|---|---|
| Sol-low coordinator across these stages | `01a087bb-3498-7570-bbbd-0e1cc57e347e` |
| sound-analyst, SIM-SOUND-001 and SIM-SOUND-002 | `01a087bd-22b1-7680-8b0a-ebef891162c9` |
| npc-charter, independent SIM-NPC-001 | `01a087c4-9d5c-7773-9a81-6548b17efcb2` |

Sol chose Luna at medium effort for both worker jobs. The related sound assignment resumed the exact existing sound worker UUID. The independent charter received a distinct worker. Genuine result receipts were recorded: sound initial `206df2c4bdba6346919b7cea248d0e9dcc1782405a95c572beefae925d0aad29`; sound follow-up `4e351bbcb495216035fdd5c8e76a1027063f9ff189ecbba7377ff41b142fcefc`; NPC charter `7f31d62d899d20cd5e11702b236fd587317c2d208ba4440299d36bb079aa9ea3`.

Manual artifact review found the assigned facts and evidence ceilings correct: sound strength 399 and aggregate drive 347 remain measurements at minute 8280 after last_checked 8225; later gate ordering remains unknown in the first result. The second result calculates admission 8585, expiry 8400 and first failure at recent-check admission, preserving unknown later gates. The NPC JSON preserves every SIM identity and the unconsumed token, contains no observed gameplay, and keeps its next action descriptive and non-executable. Both worker and coordinator performed local JSON contract validation.

| Output | Bytes | SHA-256 |
|---|---:|---|
| `npc-charter.json` | 2730 | `5a90731cf81a42c62b78cefe1fde1c53f078bd7a27a4737aa5cfada5d638af26` |
| `sound-eligibility.md` | 2397 | `1191f47484370ab4c3b9d10564549a7b142ecca78ab1ee3ed3da08f4e62aa6a8` |
| `sound-footing.md` | 1582 | `2c035aab11461cf298479913de04d5d2b9857b2acfa6f23aab73414f738570d4` |

The first sound worker also rewrote the input `evidence/sound-observation.md` from 759 to 1309 bytes, adding chronology and boundary summaries. The original numerical facts and their limits remained correct, but this duplicated interpretation into an input source. Other published sources remained exact fixture matches. The initial assignment ambiguously said “Extract ... in evidence/sound-observation.md” before specifying the output; generic packet guidance also mentioned recoverable fixture/observation repairs. Those are plausible causes of the extra edit, not proven mental causes. Future fixture wording now explicitly reads FROM the source, preserves it, and writes only the requested output.

The exact recorded worker input said “The input below is your current prepared assignment; use the delivered text directly.” Selected context was labelled optional search material, and FS/ledger reads were conditional on ambiguity or contradiction. No inspected instruction required a full canonical packet reread. The displayed canonical packet path may have cued verification; this remains an inference.

| Assignment | Canonical / delivered prepared bytes | Observed reads |
|---|---:|---|
| Initial sound | 9798 / 9798 | Full canonical packet reread; supporting context, FS and ledger; source interpretation also written into the source |
| Related sound | 11551 / 8215 | Current gate source plus retained observation and own prior artifact; no canonical packet or broad-history reread |
| Independent NPC | 10049 / 10049 | Full canonical packet reread plus unrelated sound-footing artifact |

The resumed assignment omitted 3336 bytes of unchanged standing sections. Audit source: `.de67/state/worker-library/events/22fdd6267cd74aadb850b24d9c636a69.jsonl`, first event. This measures delivery reduction, not token savings for equivalent tasks.

| Actor | Completed command calls | Command output bytes |
|---|---:|---:|
| Sol coordinator | 64 | 150079 |
| Initial sound worker task | 11 | 42368 |
| Related sound worker task | 3 | 6755 |
| NPC worker task | 5 | 22228 |

Command counts alone do not identify waste. Reused sound's first read was 4164 bytes, output verification 2492 bytes, and mailbox acknowledgement 99 bytes. The exact API audit additionally confirms real userMessage client IDs correspond to `de67-worker:<request UUID>` on both item/started and item/completed.

The inherited sound claim deadline was 1788984283.195344. The related worker returned at 1788984245.576607, 37.619 seconds before it. Coordinator terminal recording occurred at 1788984444.1091468, 160.914 seconds after it and 198.533 seconds after worker return. The task itself elapsed 290.747 seconds; initial sound task opening to terminal elapsed 300.274 seconds. Policy returned `retire_for_mutation_review`. The attempted night-footing continuation respected that gate and opened no task, dispatched no worker and produced no night artifact. These facts remain in the baseline; no gate was bypassed and no mutation review was fabricated. The baseline harness process exited 0 despite its explicit incomplete-stage report; the future harness now exits 1 for an attempted incomplete stage.

## Observed model usage

Fresh tokens mean input minus cached input plus output. Each own-response record is counted once across the exact three simulation UUIDs; counters are complete, with no missing identities or conflicting records. These totals include the stopped continuation. They exclude the earlier discarded fixture probe, outer development/review work, and any future proof. They do not imply billing cost or a matched efficiency comparison.

| Model | Input | Cached input | Output | Fresh |
|---|---:|---:|---:|---:|
| gpt-5.6-sol | 2866910 | 2778112 | 20484 | 109282 |
| gpt-5.6-luna | 778714 | 683264 | 8324 | 103774 |

Total observed fresh tokens: **213056**.

## Revised candidate: night continuity and corrected premise

Workspace: `/Volumes/CodexBulk/Schanigarten/workspaces/de67-worker-library-sim-20260909-night-final`; immutable candidate: `candidate-v2`. The explicit `--from night-footing` selection ran only the remaining two stages. Both completed with exit 0, genuine receipts and no missing artifacts. Candidate hashes are identical across the two stages. Raw report: `protocol/observations.json`; complete accounting: `protocol/restart-correction-after.json`.

| Role | Actual model session UUID |
|---|---|
| Sol-low coordinator, night-footing | `01a087d2-04d3-73d0-84b5-84919ae5710c` |
| Sol-low coordinator, restart-correction | `01a087d8-72b0-7232-a21f-f9c1d6991aa4` |
| night-evidence-analyst, both assignments | `01a087d4-2c8a-7933-9ac7-fc0c2dc3b759` |

The second coordinator is fresh (isolated restart generation 1), while both assignments claim the same actual Luna-medium worker UUID. Fresh Sol selected that retained analyst, sent an explicit correction that the production caller exists, and received the worker's explicit acknowledgment. The corrected artifact names `src/do_turn.cpp::advance_live_bandit_hostile_approaches`, invoked by `overmap_npc_move`; it rejects the old missing-caller explanation as an established cause, preserves rallying and replacement continuity, and leaves the first failed prerequisite unknown. It distinguishes intended departure/reload behavior from proof, proposes no duplicate caller, and makes no gameplay-repair, approach, contact, or feel claim.

Both evidence source files remain byte-for-byte equal to the published fixture. Initial `night-footing.md` has one wording limit: “Each crossed a same-world replacement process” is stronger than the supplied aggregate replacement evidence. Per-run replacement cardinality is not established. The corrected artifact uses the supplied aggregate wording and does not repeat “Each”. This does not affect the measured worker/restart identity facts.

| Output | Bytes | SHA-256 |
|---|---:|---|
| `night-corrected.md` | 2692 | `54c64aa992c7736ae011ad723771e4cb90b547048efc2985a40adc119c4ff01d` |
| `night-footing.md` | 1844 | `d4c7ac3e816b7b2994b3ffb6301ecd1c04583ea0f60e53a7e7d69a76bb5120d4` |

Genuine receipts: initial `1f2dd50ce02e14f6e64c0b070a2b4c5abf3887c7976d9b692d4aa975c77266c1`; corrected `d926fedb52a07d4f12199f7273f6eb4b6941a9c5306713f3d9b567596a3e8859`.

Sol chose 900 seconds for the initial whole-claim clock after receiving the two-stage/restart scope and measured earlier timings, and 300 seconds for the second task. Neither estimate was imposed by the test harness. The original claim deadline 1788986087.029203 stayed unchanged. Initial terminal recording was 1788985429.652012; second terminal recording was 1788985857.610193, leaving 229.419 seconds. The policy's repeated display of a completed task result caused extra routing inspection; it did not prevent the test boundary or cause a duplicate terminal transition.

The new worker received 10005 prepared bytes and did not reread its canonical packet. Its four command calls produced 3592 bytes. On reuse, 12124 canonical bytes became 8685 delivered bytes by omitting 3439 unchanged standing bytes. Three commands produced 6999 bytes: reading the correction plus prior footing/observation 4101, checking the output 2799, and mailbox acknowledgment 99. Neither night assignment reread the canonical packet; the coordinator made 47 command calls with 126323 output bytes. These are observed reading/delivery differences across distinct tasks and instruction versions, not a controlled token-savings benchmark.

| Model | Input | Cached input | Output | Fresh |
|---|---:|---:|---:|---:|
| gpt-5.6-sol | 2003872 | 1881088 | 20434 | 143218 |
| gpt-5.6-luna | 308922 | 280832 | 3685 | 31775 |

Night-run fresh tokens: **174993**. All three exact sessions have complete own-response accounting and no gaps. The two reported live runs together used **388049** observed fresh tokens, excluding the earlier discarded fixture probe and outer development/review.

Assignment-scoped accounting was independently audited and checked against the saved `token_usage` snapshot: the successor coordinator contributes 73471 fresh tokens and the current night-worker assignment contributes 12679, totaling **86150**. Its five worker responses exclude six responses from the earlier assignment (19096 fresh tokens). Those earlier tokens remain in the complete whole-run total. No helper sessions or accounting gaps were found. This verifies that reusing a worker does not attribute its prior assignment tokens to the current coordinator window.

## Final-reply collection defect and replay evidence

The real API emitted substantive `agentMessage` finals with `phase=final_answer`. Both immutable candidates' collectors omitted that phase, so their stored worker result files say `No final worker message was returned.` despite the actual final messages and produced artifacts. Sol used the worker's mailbox report and independently inspected artifacts when creating its receipts. UUID continuity and artifact correction do not by themselves prove correct final-text delivery.

`actual-worker-final-frames.json` captures 15 exact public final-message/terminal frames from all five completed assignments, with each audit source/hash and the corresponding stored placeholder path/text/hash. Every source audit still matched its captured hash after the night run ended. It includes no private reasoning. The corrected collector passed replay of all five assignments and all 15 captured frames in original order (`item/started`, `item/completed`, `turn/completed`). Each replay used separate temporary DeadlineHarness and worker-registry state, preserved the actual thread/turn IDs and public text, produced status `returned`, and stored a final text whose SHA-256 exactly matched the captured substantive reply. Every task remained nonterminal: a worker return did not exercise coordinator terminal authority. Each receiving fixture used one simulated transport-start receipt, and temporary state was cleaned afterward. This is deterministic replay of real events, with no additional live model call. Results and per-text hashes are in `actual-worker-final-replay-report.json`; the Windows replay script is archived as `replay_actual_worker_finals.py` and expects the adjacent `de67` test package in its original workspace.

Both outer simulation processes have exited. No production restart was performed. The staged fixture correction with an actual isolated coordinator restart establishes coordination continuity, not an actual mutation review or production method promotion.


Earlier setup probe accounting (independently rechecked by root): the discarded non-Git pilot in `de67-worker-library-sim-20260909` consumed 107,893 fresh tokens: Sol 70,075 and Luna 37,818. Its saved own-response telemetry is complete, and the runtime records contain no helper edges for those two sessions. It remains useful as setup/dispatch evidence, not a comparable efficiency run, because broad searches entered unignored runtime state.

Including that pilot, all three observed coordinator/worker probe runs consumed 495,942 fresh tokens (107,893 + 213,056 + 174,993). This excludes outer implementation, code review and engineering subagents. The reported baseline+night subtotal remains 388,049. Neither total establishes savings against a control.

Root reran all 15 captured final frames from the five reported assignments against the final candidate collector. Every final text matched exactly and no task was terminalized by replay. `actual-worker-final-replay-report.json` now also records the final `worker_library.py` SHA-256.
