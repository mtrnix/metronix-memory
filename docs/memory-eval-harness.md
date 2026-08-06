# Unified memory evaluation harness

`scripts/run_memory_eval.py` is the single run-level entry point for the
repository's existing memory and retrieval evaluations. It orchestrates the
native runners without changing their datasets, scoring, or artifact formats:

- `search` runs `scripts/run_eval.py` against a live Metronix workspace.
- `rag-397` runs `scripts/rag_eval_397.py` against a live authenticated REST
  API with RAG trace capture enabled.
- `longmemeval` runs the existing LongMemEval pipeline and, unless disabled,
  its external LLM judge.

The harness is not a substitute for any suite's setup. It does not start
services, provide credentials, or turn the LLM-judged suite into a deterministic
or free benchmark.

## Run a suite

Create the project virtual environment first (`make setup`), then select only
the suites whose prerequisites are available. For example, run labelled search
quality against a local stack:

```bash
make memory-eval MEMORY_EVAL_ARGS='--suites search --search-workspace MTRNIX'
```

Use an explicit report path when the report will be retained or consumed by CI:

```bash
.venv/bin/python scripts/run_memory_eval.py \
  --suites search,longmemeval \
  --search-workspace MTRNIX \
  --longmemeval-variant s \
  --longmemeval-max-questions 25 \
  --output results/memory-eval/release-candidate.json
```

Without `--output`, the report is written to
`results/memory-eval/<UTC timestamp>.json`. Native outputs are placed alongside
it in `<report stem>.artifacts/`; the unified report links to these files but
does not embed query traces, model answers, credentials, tokens, or passwords.
Child stdout and stderr are never retained in the unified report, including on
failure; failure entries contain only generic diagnostics.

## Per-suite setup and cost

### Search

`search` needs a running Metronix service stack and an indexed workspace. The
default workspace is `MTRNIX`; select another with `--search-workspace`. The
default test set is the one used by `scripts/run_eval.py`; use
`--search-testset PATH` for a labelled alternative, `--search-k N` to change
the retrieval cut-off, and `--include-unstable` to include unstable queries.

This suite's runtime depends on the size of the test set and on the live
retrieval stack. It has the same model and infrastructure usage as the existing
search evaluator.

### RAG-397

`rag-397` needs a live API with RAG trace capture enabled, a populated
workspace, and credentials exported in the shell running the command:

```bash
export METRONIX_ADMIN_EMAIL='operator@example.com'
export METRONIX_ADMIN_PASSWORD='...'
make memory-eval MEMORY_EVAL_ARGS='--suites rag-397 \
  --rag-397-base-url http://localhost:8000 \
  --rag-397-workspace MTRNIX'
```

The credentials are passed to the child runner only and are not printed or
written into the unified report. RAG-397 sends its fixed regression, positive,
and adversarial prompts to the live API, so it has the same latency and any
provider/model cost as a real RAG interaction. Do not use production accounts
or data unless that traffic is explicitly approved.

### LongMemEval

Prepare its dedicated environment and dataset as described in
[`docs/benchmarks/longmemeval.md`](benchmarks/longmemeval.md):

```bash
make bench-lme-setup
make memory-eval MEMORY_EVAL_ARGS='--suites longmemeval \
  --longmemeval-variant s --longmemeval-max-questions 25'
```

LongMemEval can take substantial time and invokes the configured external LLM
judge by default, which can incur provider charges. Use
`--longmemeval-run-only` to generate hypotheses without the judge; the report
will still record answer count, but no judged `accuracy` is available. Each
harness invocation forces its explicit LongMemEval artifact to start fresh, so
rerunning the same report path never resumes stale hypotheses.

## Read the report and select exit behavior

The JSON report has `schema_version`, timestamps, `requested_suites`, a
per-suite `suites` map, and optional `deltas`, `regressions`, and
`incompatible_suites` when a baseline is supplied. Each suite records its
status, timing, exit code, sanitized effective configuration, native artifact
path, and a small native summary.

Search quality summaries include retrieval metrics such as `mrr` and
`ndcg_at_k`. RAG-397 summaries are bucket and error counters, not a universal
quality score. LongMemEval records answer count and, when the judge prints it,
accuracy. Any RAG-397 case carrying an `error` key, regardless of its value, or
any LongMemEval hypothesis that begins with `Error:` fails its suite even when
the child process exits zero. A judged LongMemEval run also fails unless the
judge emits a finite accuracy. Keep these metrics separate: the harness
deliberately does not blend them into one score.

The command exits:

- `0` when all selected suites pass and no configured quality gate is breached.
- `1` when a selected suite fails, an explicit regression threshold is
  breached, or a configured gate cannot be evaluated; the completed report is
  still written.
- `2` for invalid arguments or configuration, including an unknown suite,
  invalid threshold, `--max-regression` without `--baseline`, a gate for an
  unselected suite, malformed baseline, or missing RAG-397 credential
  environment variables. No suite starts in this case.

The command continues selected suites after a runtime failure so the report
captures the whole requested run.

## Baselines and CI gates

Pass a prior harness report with `--baseline`. A suite is comparable only when
both its current and baseline status are `passed` and its recorded relevant
configuration is identical after normalization. Compatible same-key numeric
metrics are included as informational deltas. Incompatible suites are listed
in `incompatible_suites`; their deltas and gates are not evaluated. A
configured gate for an incompatible suite fails closed with exit code `1`.
For LongMemEval, compatibility includes the workspace, retrieval `top_k`, chat
and judge model/base URLs, and dataset filename/source/content SHA-256 in
addition to the variant, question limit, and judge mode. Secret values are
never recorded.
Compatible metrics only become CI gates when you provide one or more
`--max-regression suite.metric=decline` values.
Thresholds are accepted only for the higher-is-better quality metrics:

- `search.precision_at_k`
- `search.mrr`
- `search.ndcg_at_k`
- `search.negative_accuracy`
- `longmemeval.accuracy`

For example, fail CI if search MRR drops by more than 0.02 or judged
LongMemEval accuracy drops by more than 0.03:

```bash
.venv/bin/python scripts/run_memory_eval.py \
  --suites search,longmemeval \
  --baseline artifacts/main-memory-eval.json \
  --max-regression search.mrr=0.02 \
  --max-regression longmemeval.accuracy=0.03 \
  --output results/memory-eval/ci.json
```

An omitted or non-numeric metric has no informational delta; if a threshold is
configured for that metric, the gate fails closed and the incompatibility is
recorded. An unjudged LongMemEval run is valid only with
`--longmemeval-run-only`; a judged run without a parsed accuracy fails. RAG-397
counters are useful for inspection but intentionally cannot be configured as
generic quality gates.
