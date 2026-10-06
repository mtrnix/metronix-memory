# Answer accuracy runs (EM / F1)

Per-question reader results behind §8 of
`../../findings/2026-09-30-answer-accuracy-note.md`: one gzipped JSONL per dataset and
configuration, one line per question, `{"qid", "answer", "em", "f1"}` (`answer` is the
text after `Answer:` in the reader's response; EM / F1 with SQuAD / HippoRAG
normalisation, maximum over the gold answer and its aliases).

| file | questions | configuration |
| --- | --- | --- |
| `musique_confirm_A_bfs_signal.jsonl.gz` | MuSiQue confirm half, 500 | A, production `bfs:signal` |
| `musique_confirm_B_learned_pprplus.jsonl.gz` | MuSiQue confirm half, 500 | B, learned fusion + "ppr+" |
| `2wiki_first300_A_bfs_signal.jsonl.gz` | 2Wiki, first 300 in manifest order | A |
| `2wiki_first300_B_learned_pprplus.jsonl.gz` | 2Wiki, first 300 in manifest order | B |

Reader responses, prompts and retrieved lists are not stored; the commands in §8.4 of the
note regenerate them. `answer_eval.py compare` needs the full `read` output (with `top`),
so to re-run the statistics from these files alone, pair the rows by `qid` and use
`compare_runs.bootstrap_ci` / `sign_test` on the `f1` / `em` differences.
