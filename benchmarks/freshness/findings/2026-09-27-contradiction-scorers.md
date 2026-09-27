# Telling contradictions from duplicates in the freshness Reconciler (#516)

Date: 2026-09-27. Branch `freshness/nli-conflict-split`. CPU only (4 cores),
qwen2.5:3b and nomic-embed-text on Ollama 0.34.4.

## Question

The Reconciler files every pair of records above a cosine gate (0.85) as
`possible_duplicate`. Does that gate also catch updates that contradict an older
record? And which cheap scorer can split the two?

## Method

Both scripts replay the Reconciler's candidate step with Metronix's own embedding
(`get_cached_embedding`, raw text, as memory records are stored and searched).

**Updates and look-alikes.** `conflict_pairs.py` runs on MemoryAgentBench
FactConsolidation, `factconsolidation_sh_32k`:
- 2,310 MQuAKE facts, among them counterfactual edits such as "X is married to A"
  → "X is married to B";
- every fact's top-10 neighbours at cosine ≥ 0.85 form the candidate pairs;
- each pair is labelled from the parsed (relation, subject, object) triples: all
  2,310 facts parse against the 37 MQuAKE templates.

**Duplicates.** `paraphrase_pairs.py` checks that duplicates stay duplicates:
- input is the human-labelled paraphrase pairs of MRPC (GLUE test split, 1,147
  pairs);
- the 903 pairs at cosine ≥ 0.85 are what the Reconciler would file as duplicates;
- every contradiction flag on them is a false one.

The scorers are the ones in `metronix.freshness.contradiction`:
- `nli`: `cross-encoder/nli-deberta-v3-xsmall`, both reading orders, threshold 0.5;
- `llm`: a yes/no prompt to qwen2.5:3b;
- `nli+llm`: the LLM judge only on the pairs NLI flags.

## Results

**Updates and look-alikes** (FactConsolidation, 936 pairs above the gate):

| | flagged | precision | recall | F1 |
| --- | --- | --- | --- | --- |
| cosine only (current) | 0 | — | 0.000 | 0.000 |
| `nli` | 866 | 0.674 | 0.988 | 0.802 |
| `llm` | 594 | 0.953 | 0.958 | 0.955 |
| `nli+llm` | 591 | 0.954 | 0.954 | 0.954 |

- **What the gate lets through.** Of the 936 pairs, 591 (63%) are updates of the
  same fact and 345 are other facts with the same relation. None are duplicates. The
  current Reconciler files all 936 as duplicates and writes an `ALIAS` edge for
  each.
- **What the gate misses.** Only 591 of all 837 update pairs (70.6%) pass the gate.
  The other 29% never reach a scorer: the cosine gate caps recall.
- **How `nli` fails.**
  - It flags 282 of the 345 non-conflicting pairs; 327 of those 345 share the
    relation but not the subject ("Denmark is in Europe" / "Sweden is in Europe").
  - That is an artifact of NLI training data, where a swapped subject is a
    contradiction.
  - Larger NLI models do not remove it. On 8 such pairs: deberta-v3-small flagged
    8/8, deberta-v3-base 7/8, DeBERTa-v3-base-mnli-fever-anli 6/8.
- **`llm` on the same look-alikes:** it flags 28 of the 345.

**Duplicates** (MRPC paraphrases, 903 pairs above the gate):

| | false contradictions | LLM calls |
| --- | --- | --- |
| `nli`, all 903 pairs | 91 (10.1%) | 0 |
| `nli`, 300-pair sample | 30 (10.0%) | 0 |
| `llm`, same sample | 12 (4.0%) | 300 |
| `nli+llm`, same sample | 7 (2.3%) | 30 |

Some MRPC "paraphrases" differ in numbers or details, so not every flag here is
wrong. The comparison between scorers still holds.

**Cost.** The gate passed 0.41 pairs per record on FactConsolidation.

| scorer | per pair | per 1,000 records |
| --- | --- | --- |
| `nli` | 21–39 ms | ~9 s |
| `llm` | 0.7–1.0 s | ~4.7 min |
| `nli+llm`, update-heavy data (NLI flags 93% of pairs) | | ~4.5 min |
| `nli+llm`, duplicate-heavy data (NLI flags 10%) | | ~1 min |

For scale: graph extraction of 1,000 passages with the same model is ~12.5 h
(~45 s each).

## Conclusion

- **Cosine alone.** It cannot tell an update from a duplicate. Most of what it files
  as duplicates on update-heavy data are contradictions.
- **NLI alone.** It is not enough: it cannot tell "the same subject changed" from
  "another subject, same predicate".
- **The cascade.** `nli+llm` matches the LLM judge on updates (F1 0.954 vs 0.955)
  and has the fewest false contradictions on duplicates (2.3%). It calls the LLM
  only where NLI objects: 10% of duplicate pairs, 93% of update pairs. It is the
  default scorer when the feature is enabled.
- **The LLM call.** The premise "no LLM call" does not survive the data. But the LLM
  runs per gated pair, not per chunk, and costs under 1% of graph extraction.

## Limitations

- Two datasets:
  - FactConsolidation is templated Wikidata facts;
  - MRPC is news sentences.
  
  A Metronix workspace (tickets, chat memories) is neither; no agent-memory dataset
  with labelled duplicate/update pairs was used.
- **The recall ceiling is the gate.** 29% of updates stay below 0.85. Lowering the
  gate trades that against more pairs to score; not measured here.
- **Only whether two records conflict is measured.** Which one is current is not:
  "the later record wins" holds in FactConsolidation by construction and is not
  safe across sources (see #516).
- **Single run.** The LLM judge at temperature 0; no repeated runs, no confidence
  intervals.

## Reproduce

```bash
# FactConsolidation: data/Conflict_Resolution-00000-of-00001.parquet from the
# ai-hyz/MemoryAgentBench dataset on the HF hub
python -m benchmarks.freshness.conflict_pairs --parquet <parquet> \
  --source factconsolidation_sh_32k --llm-sample 100000 --output <out>.json
# MRPC: mrpc/test-00000-of-00001.parquet from nyu-mll/glue
python -m benchmarks.freshness.paraphrase_pairs --parquet <mrpc test parquet> \
  --llm-sample 300 --output <out>.json
```

The LLM judge goes through `chat_completion` (`LLM_PROVIDER=ollama`,
`OLLAMA_LLM_MODEL=qwen2.5:3b`). Result files: `../results/2026-09-27/`.
