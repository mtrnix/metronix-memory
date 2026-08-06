# Unified Memory Evaluation Harness

## Purpose

Issue #309 needs one repeatable entry point for the repository's existing
memory and retrieval evaluations. Version one wraps their current behavior;
it does not replace their domain-specific runners or change their scoring.

## Scope

The new root-level CLI, `scripts/run_memory_eval.py`, runs any selected subset
of these suites:

1. `search`: `scripts/run_eval.py`, which measures labelled retrieval quality
   for a live workspace.
2. `rag-397`: `scripts/rag_eval_397.py`, which exercises authenticated REST
   chat and RAG traces with its regression, positive, and adversarial buckets.
3. `longmemeval`: the existing LongMemEval runner and judge under
   `benchmarks/longmemeval/`.

Each suite retains its existing prerequisites, configuration, native artifact
format, and scoring semantics. The harness only orchestrates it and exposes a
consistent run-level contract.

## Command-line interface

`python scripts/run_memory_eval.py` accepts a comma-separated `--suites` list
and defaults to all three suites. It writes a versioned report to an explicit
`--output` path or to a timestamped file under `results/memory-eval/`.

The CLI defines explicit, non-secret configuration for the selected suite:

- search: workspace, test-set path, top-K, and whether unstable queries are
  included;
- rag-397: base URL, workspace, and the paths or environment-variable names
  used for credentials (never their values);
- LongMemEval: variant, maximum questions, output path, and whether the judge
  runs.

Credentials remain in environment variables or the existing benchmark env
file. They are supplied to child processes without being printed or persisted
in the unified report.

## Report contract

The report is JSON with a schema version and run metadata (`started_at`,
`finished_at`, duration, harness version, requested suites). `suites` is a
mapping keyed by suite name. Every suite entry contains:

- `status`: `passed`, `failed`, or `skipped`;
- timing and child-process exit code;
- sanitized effective configuration and native artifact paths;
- a suite-specific `summary` containing parsed metrics or counters;
- a diagnostic error message when execution or result parsing failed.

The raw native outputs stay in their current paths. The report links to them
rather than embedding secrets, full model answers, or high-volume traces.

## Baselines and CI behavior

`--baseline <report.json>` adds deltas for compatible metrics from a previous
harness report. The harness does not infer a universal quality score: search
retrieval metrics, RAG trace checks, and LLM-judged LongMemEval scores remain
separate.

`--max-regression suite.metric=value` supplies explicit acceptance thresholds.
Without thresholds, baseline comparisons are informational. A selected suite
failure or a threshold breach returns a non-zero exit code, making the command
suitable for CI; otherwise it exits zero.

Argument validation fails before a child process starts. Once a run begins,
the harness continues after a suite failure and records each selected suite in
the same report. Missing optional prerequisites produce a clear failed or
skipped suite record according to whether the user selected that suite.

## Implementation boundaries

The orchestrator is deliberately small and uses subprocess boundaries around
the existing scripts. It owns selection, argument validation, environment
passing, artifact discovery, result normalization, baseline comparison, and
exit status. Existing evaluators continue to own retrieval behavior, RAG
requests, dataset ingestion, judge invocation, and their native output.

To keep the code testable, the CLI will delegate report construction,
subprocess execution, parsing, and comparison to focused functions or a small
support module. No new third-party dependency is required.

## Tests and documentation

Unit tests will mock child-process execution and cover command construction,
sanitization, successful mixed-suite reports, partial failures, malformed
artifacts, baseline compatibility, regression thresholds, and exit codes.

Documentation will list per-suite setup, expected runtime and external cost,
report locations, metric interpretation, threshold examples, and a CI command.
It will explicitly state that a live Metronix stack and relevant credentials
are still required for real runs.

## Non-goals

- Rewriting the three evaluators into a common scoring framework.
- Making LongMemEval deterministic or free of external LLM costs.
- Treating RAG-397's project-specific queries as a generic benchmark.
- Running live benchmark services in the unit-test suite.
