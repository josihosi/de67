# Alignment audit reviewer brief

Use independent reviewers when the repository is large enough that separate active workflow owners
can be inspected concurrently. Prefer Luna with maximum reasoning effort when available. Partition
by coherent ownership—such as coordination/supervision, a domain harness, and applicable repository
policy—not by arbitrary file counts. Do not give several reviewers the same undifferentiated tree.

Every reviewer reads the alignment manifest before its assigned surfaces. Give each reviewer:

- the exact repository or installed-skill root;
- the workflow lane and active entrypoints it owns;
- applicable exclusions and side-effect constraints;
- the paired machine-output producers and consumers;
- the active tests that enforce the lane;
- the required finding format from the audit entrypoint.

Reviewers work read-only. They must not launch scenarios, consume tokens, wake or stop agents,
modify ledgers, or repair findings. They may inspect live process truth when authorized and when the
inspection is non-mutating.

## Scope by discovery path

Map the active instruction graph before reading broadly:

1. Start with applicable host and repository agent policy.
2. Follow only the selected skill route and its direct references.
3. Locate generated prompts, command descriptors, status responses, errors, dashboards, or TUIs
   through which the machine speaks back to the agent.
4. Locate tests covering those producers, consumers, and transitions.
5. Follow historical material only when an active surface links to it or an agent is realistically
   instructed to discover it.

Classify surfaces rather than treating every Markdown file as policy. Product documentation,
upstream history, release prose, and unrelated skills are normally outside scope. A legacy document
is material when it can masquerade as live authority; otherwise omit it.

## Evidence discipline

Do not infer runtime behavior from a symbol name or assignment alone. Trace the active command,
branch, step type, call chain, and emitted interface. Distinguish automated setup from agent-owned
execution, canonical probes from live sessions, and historical fixtures from ordinary gates.

Use observed behavior as evidence, including user observations, but reconcile it with code rather
than privileging either source automatically. Withdraw or narrow findings disproved by the complete
route. Report rejected concerns: they demonstrate that the audit can falsify its own suspicions.

Tests deserve the same scrutiny as prose. Retain assertions protecting mechanical truth and real
safety boundaries. Flag assertions that constitutionalize exact prose, one model profile, one
strategy, one task order, proof-shaped ceremony, obsolete schemas, or arbitrary limits without an
authoritative source.

## Synthesis

The lead reviewer deduplicates findings, resolves disagreements by tracing the runtime route, and
reports:

- whether the manifest exposed real cross-layer contradictions;
- necessary corrections ordered by the user-visible failure they prevent;
- strict mechanical invariants worth preserving;
- strategy and judgment that should return to agents;
- legacy residue to delete, relocate, or mark;
- rejected findings and why they failed the evidence test.

Do not turn the manifest into production prompt cargo. It is an occasional lens for improving the
instruction system, not another supervisor or policy constitution.
