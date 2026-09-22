# Initial validation — 2026-09-18

Implementation and checks ran on macOS using Python 3 and ripgrep. No Windows/Linux
runtime was available for this pass; implementation uses portable standard-library
APIs and the existing `rg` executable contract.

- `python3 -m unittest discover -s integrations/jev_telescope -p 'test_*.py'`:
  19 deterministic tests passed, without credentials or network. Includes a real
  short-lived process timeout/cleanup test and HTTP request/response contract tests.
- `python3 -m unittest discover -s de-67-3/tests -p 'test_*context.py'`:
  12 existing context tests passed; disabled integration preserves existing prompts.
- `python3 integrations/jev_telescope/evaluate.py --output /tmp/telescope-baseline.json`:
  all four real-repository cases retrieved their declared important anchors.
- Live paired evaluation: four requests, same candidate pools and 4,800-byte excerpt
  budget per arm, no retries, no fallbacks. Model requested: `jev-latest`.

| Case | Baseline / Jev labeled coverage | Baseline / Jev returned items | Jev selection + verification |
| --- | --- | --- | --- |
| Worker unloading and reuse | 100% / 100% | 6 / 6 | 1.066 s |
| Owner bootstrap on resume | 100% / 100% | 4 / 4 | 0.983 s |
| Misleading WEC hypothesis | 100% / 100% | 2 / 2 | 1.011 s |
| Irrelevant symbol-codec pool | not applicable | 7 / 0 | 0.972 s |

No labeled important or counterevidence excerpt was missed. Jev correctly abstained
on the irrelevant-only pool; baseline did not. Other cases produced the same evidence
size as baseline. Baseline retrieval/verification took approximately 18–32 ms per case;
that local retrieval cost also applies before Jev selection. Provider usage totaled
11,546 input tokens and 2,350 output tokens. Detailed candidate locations/hashes and
usage are in `evaluation-results.json`; no credentials or source excerpts are stored there.

The labels identify a small set of important excerpts, not an exhaustive relevance
annotation. Unlabeled results may still be useful. This sample establishes a working
adapter and one successful abstention example, not calibrated quality or an efficiency
win. Full agent task quality, subsequent recovery searches, total agent tokens/cost,
and end-to-end elapsed time remain unmeasured. Stubbed tests prove behavior under the
stub, not Jev's selection quality. External transmission remains off by default.
