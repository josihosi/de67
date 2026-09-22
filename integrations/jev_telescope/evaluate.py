#!/usr/bin/env python3
"""Paired fixed-pool evaluation. Default is local baseline only; --live authorizes transmission."""
import argparse
import json
from pathlib import Path
import time

import telescope as t


def metrics(packet, pool, anchors, counter_anchors):
    important = {c["id"] for c in pool if any(a in c["excerpt"] for a in anchors)}
    counter = {c["id"] for c in pool if any(a in c["excerpt"] for a in counter_anchors)}
    returned = {c["id"] for c in packet["items"]}
    return dict(coverage=len(important & returned) / len(important) if important else None,
                missed_important_ids=sorted(important - returned),
                missed_counterevidence_ids=sorted(counter - returned),
                labeled_relevant_count=len(important), returned_count=len(returned),
                unlabeled_return_count=len(returned - important),
                abstention_correct=(not returned) == (not important),
                latency_seconds=packet["elapsed_seconds"], provider_calls=packet["provider_calls"],
                provider_usage=packet["provider_usage"], fallback=packet["fallback"],
                evidence_bytes=packet["evidence_bytes"])


def run(workspace, live=False, cases_path=None, call=t.bounded_provider):
    cases_path = cases_path or Path(__file__).with_name("evaluation.json")
    cases = json.loads(cases_path.read_text())["cases"]
    results = []
    for case in cases:
        config = t.validate_config(dict(paths=case["paths"], max_candidates=16, candidate_bytes=2400,
                                       evidence_bytes=4800, elapsed_seconds=20, cache_seconds=0))
        start = time.monotonic()
        pool, info = t.gather(workspace, case["query"], case["terms"], config, start + config["elapsed_seconds"])
        missing_anchors = [a for a in case["important_anchors"] if not any(a in c["excerpt"] for c in pool)]
        baseline = t.evaluate(workspace, case["query"], case["hypothesis"], pool, info, config, started=start)
        row = dict(id=case["id"], candidate_pool=[{k: c[k] for k in ("id", "path", "sha256", "start", "end")} for c in pool],
                   missing_label_anchors=missing_anchors, retrieval_seconds=time.monotonic() - start,
                   baseline=metrics(baseline, pool, case["important_anchors"], case["counter_anchors"]))
        if live:
            selected = t.evaluate(workspace, case["query"], case["hypothesis"], pool, info,
                                  {**config, "mode": "on"}, call=call)
            row["jev"] = metrics(selected, pool, case["important_anchors"], case["counter_anchors"])
        results.append(row)
    return dict(provider_requested=live, provider_evaluated=live and any(not row["jev"]["fallback"] for row in results), cases=results,
                fallback_frequency=sum(bool(r.get("jev", {}).get("fallback")) for r in results) / len(results) if live else None,
                efficiency_claim="Unverified. This measures retrieval only; representative agent task quality, recovery searches, total agent usage and end-to-end elapsed time are not measured.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--live", action="store_true", help="Send the four bounded public-repository candidate pools to TypeSafe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = run(args.workspace.resolve(), args.live)
    if args.output:
        t.save_json(args.output, value)
    else:
        print(json.dumps(value, indent=2))
    return 1 if any(case["missing_label_anchors"] or case.get("jev", {}).get("fallback") for case in value["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
