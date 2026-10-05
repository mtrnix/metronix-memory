"""Answer accuracy (EM / F1) of a retrieval configuration with a fixed reader LLM.

``pipeline_probe --keep-top 5`` records the final top 5 passages per question; this script
hands them to one reader model with HippoRAG 2's QA prompt and scores the answer with the
standard SQuAD / HippoRAG normalisation (lower case, no punctuation, no articles, collapsed
whitespace), taking the maximum over the gold answer and its aliases.

Sub-commands:

``read``     run the reader over a ``pipeline_probe`` output; one JSON line per question
             (resumable: questions already in ``--output`` are skipped). Identical prompts
             are answered once (``--prompt-cache``): with temperature 0 the reader is a
             function of the prompt, so two configurations with the same top 5 for a
             question get the same answer.
``compare``  paired comparison of two ``read`` outputs: mean EM / F1, the per-question
             difference B - A with a bootstrap 95% CI and an exact two-sided sign test
             (``compare_runs.bootstrap_ci`` / ``sign_test``), overall and per group.
``export``   compact per-question results (qid, answer, EM, F1) as gzipped JSONL.

The prompt (system message, one-shot example, ``Wikipedia Title: <title>\\n<text>`` per
passage, ``Question: ... \\nThought: ``) and the answer extraction (text after the first
``Answer:``, else the whole response) are HippoRAG 2's ``rag_qa_musique`` template and
``HippoRAG.qa`` (github.com/OSU-NLP-Group/HippoRAG, commit 398bfdc, MIT licence), which
HippoRAG 2 uses for MuSiQue and 2Wiki alike.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import string
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from benchmarks.musique.scripts.compare_runs import bootstrap_ci, sign_test
from benchmarks.musique.scripts.hipporag_set import load_corpus

# --- HippoRAG 2 rag_qa_musique template (verbatim) -------------------------------------

_ONE_SHOT_DOCS = (
    """Wikipedia Title: The Last Horse\nThe Last Horse (Spanish:El último caballo) is a 1950 Spanish comedy film directed by Edgar Neville starring Fernando Fernán Gómez.\n"""  # noqa: E501
    """Wikipedia Title: Southampton\nThe University of Southampton, which was founded in 1862 and received its Royal Charter as a university in 1952, has over 22,000 students. The university is ranked in the top 100 research universities in the world in the Academic Ranking of World Universities 2010. In 2010, the THES - QS World University Rankings positioned the University of Southampton in the top 80 universities in the world. The university considers itself one of the top 5 research universities in the UK. The university has a global reputation for research into engineering sciences, oceanography, chemistry, cancer sciences, sound and vibration research, computer science and electronics, optoelectronics and textile conservation at the Textile Conservation Centre (which is due to close in October 2009.) It is also home to the National Oceanography Centre, Southampton (NOCS), the focus of Natural Environment Research Council-funded marine research.\n"""  # noqa: E501
    """Wikipedia Title: Stanton Township, Champaign County, Illinois\nStanton Township is a township in Champaign County, Illinois, USA. As of the 2010 census, its population was 505 and it contained 202 housing units.\n"""  # noqa: E501
    """Wikipedia Title: Neville A. Stanton\nNeville A. Stanton is a British Professor of Human Factors and Ergonomics at the University of Southampton. Prof Stanton is a Chartered Engineer (C.Eng), Chartered Psychologist (C.Psychol) and Chartered Ergonomist (C.ErgHF). He has written and edited over a forty books and over three hundered peer-reviewed journal papers on applications of the subject. Stanton is a Fellow of the British Psychological Society, a Fellow of The Institute of Ergonomics and Human Factors and a member of the Institution of Engineering and Technology. He has been published in academic journals including "Nature". He has also helped organisations design new human-machine interfaces, such as the Adaptive Cruise Control system for Jaguar Cars.\n"""  # noqa: E501
    """Wikipedia Title: Finding Nemo\nFinding Nemo Theatrical release poster Directed by Andrew Stanton Produced by Graham Walters Screenplay by Andrew Stanton Bob Peterson David Reynolds Story by Andrew Stanton Starring Albert Brooks Ellen DeGeneres Alexander Gould Willem Dafoe Music by Thomas Newman Cinematography Sharon Calahan Jeremy Lasky Edited by David Ian Salter Production company Walt Disney Pictures Pixar Animation Studios Distributed by Buena Vista Pictures Distribution Release date May 30, 2003 (2003 - 05 - 30) Running time 100 minutes Country United States Language English Budget $$94 million Box office $$940.3 million"""  # noqa: E501
)
_SYSTEM = (
    "As an advanced reading comprehension assistant, your task is to analyze text passages "
    "and corresponding questions meticulously. "
    'Your response start after "Thought: ", where you will methodically break down the '
    "reasoning process, illustrating how you arrive at conclusions. "
    'Conclude with "Answer: " to present a concise, definitive response, devoid of '
    "additional elaborations."
)
_ONE_SHOT_INPUT = (
    f"{_ONE_SHOT_DOCS}\n\nQuestion: When was Neville A. Stanton's employer founded?\nThought: "
)
_ONE_SHOT_OUTPUT = (
    "The employer of Neville A. Stanton is University of Southampton. The University of "
    "Southampton was founded in 1862. "
    "\nAnswer: 1862."
)


def qa_messages(question: str, passages: list[str]) -> list[dict[str, str]]:
    """HippoRAG 2 QA messages; ``passages`` are ``title\\ntext`` strings in rank order."""
    user = "".join(f"Wikipedia Title: {p}\n\n" for p in passages)
    user += "Question: " + question + "\nThought: "
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _ONE_SHOT_INPUT},
        {"role": "assistant", "content": _ONE_SHOT_OUTPUT},
        {"role": "user", "content": user},
    ]


def extract_answer(response: str) -> str:
    """HippoRAG's extraction: the text after the first ``Answer:``, else the response."""
    parts = response.split("Answer:")
    return parts[1].strip() if len(parts) > 1 else response


# --- SQuAD / HippoRAG answer metrics ---------------------------------------------------


def normalize_answer(text: str) -> str:
    text = str(text).lower()
    text = "".join(ch for ch in text if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact_match(gold: list[str], predicted: str) -> float:
    pred = normalize_answer(predicted)
    return max((float(normalize_answer(g) == pred) for g in gold), default=0.0)


def _f1(gold: str, predicted: str) -> float:
    gold_tokens = normalize_answer(gold).split()
    pred_tokens = normalize_answer(predicted).split()
    same = sum((Counter(pred_tokens) & Counter(gold_tokens)).values())
    if same == 0:
        return 0.0
    precision = same / len(pred_tokens)
    recall = same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def f1_score(gold: list[str], predicted: str) -> float:
    return max((_f1(g, predicted) for g in gold), default=0.0)


def gold_answers(dataset_path: Path) -> dict[str, list[str]]:
    """qid -> answer plus ``answer_aliases``, as HippoRAG's ``get_gold_answers``."""
    with dataset_path.open(encoding="utf-8") as handle:
        records = json.load(handle)
    out = {}
    for r in records:
        qid = r.get("id", r.get("_id"))
        answer = r["answer"]
        answers = [answer] if isinstance(answer, str) else list(answer)
        answers.extend(r.get("answer_aliases") or [])
        out[qid] = list(dict.fromkeys(answers))
    return out


# --- reader -----------------------------------------------------------------------------


def prompt_key(model: str, options: dict, messages: list[dict]) -> str:
    blob = json.dumps({"model": model, "options": options, "messages": messages}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def model_digest(host: str, model: str) -> str | None:
    with urllib.request.urlopen(f"{host}/api/tags", timeout=30) as resp:
        tags = json.load(resp)
    for m in tags.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return m.get("digest")
    return None


def ollama_chat(host: str, model: str, messages: list[dict], options: dict) -> dict:
    body = json.dumps(
        {"model": model, "messages": messages, "stream": False, "options": options}
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=1800) as resp:
        return json.load(resp)


def prime(host: str, model: str, options: dict) -> None:
    """Leave the fixed QA prefix (system + one-shot) in Ollama's KV cache.

    Ollama reuses the cached prefix shared with the previous request, and with temperature
    0 the output still depends on where that reuse stops (the pilot of 2026-09-30: 6 of 20
    repeated prompts gave different text, 3 a different answer). Sending this primer
    before every question makes the reused prefix the same for every prompt, so each
    prompt has one answer whatever ran before it.
    """
    messages = qa_messages("", [])[:3] + [{"role": "user", "content": ""}]
    ollama_chat(host, model, messages, {**options, "num_predict": 1})


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read(args: Any) -> None:
    run = json.loads(args.run.read_text(encoding="utf-8"))
    rows = run["rows"][: args.limit] if args.limit else run["rows"]
    corpus = load_corpus(args.corpus, args.label_prefix)
    gold = gold_answers(args.dataset)
    options = {
        "temperature": 0,
        "seed": 0,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
    }
    digest = model_digest(args.host, args.model)
    if args.expect_digest and not (digest or "").startswith(args.expect_digest):
        raise SystemExit(f"model digest {digest} != expected {args.expect_digest}")
    done = {r["qid"] for r in _load_jsonl(args.output)}
    cache = {c["key"]: c for c in _load_jsonl(args.prompt_cache)} if args.prompt_cache else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as out:
        for row in rows:
            if row["qid"] in done:
                continue
            top = row["top"][: args.top]
            passages = [f"{corpus[label]['title']}\n{corpus[label]['text']}" for label in top]
            messages = qa_messages(args.question_of(row["qid"]), passages)
            key = prompt_key(args.model, options, messages)
            cached = key in cache
            if cached:
                resp = cache[key]
            else:
                start = time.perf_counter()
                prime(args.host, args.model, options)
                reply = ollama_chat(args.host, args.model, messages, options)
                resp = {
                    "key": key,
                    "response": reply["message"]["content"],
                    "seconds": round(time.perf_counter() - start, 2),
                    "prompt_eval_count": reply.get("prompt_eval_count"),
                    "eval_count": reply.get("eval_count"),
                }
                cache[key] = resp
                if args.prompt_cache:
                    with args.prompt_cache.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(resp, ensure_ascii=False) + "\n")
            answer = extract_answer(resp["response"])
            result = {
                "qid": row["qid"],
                "answer": answer,
                "em": exact_match(gold[row["qid"]], answer),
                "f1": round(f1_score(gold[row["qid"]], answer), 4),
                "top": top,
                "response": resp["response"],
                "prompt_key": key,
                "cached": cached,
                "seconds": 0.0 if cached else resp["seconds"],
                "prompt_eval_count": resp.get("prompt_eval_count"),
                "eval_count": resp.get("eval_count"),
                "model": args.model,
                "model_digest": digest,
            }
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            out.flush()
            print(
                f"{row['qid']} em={result['em']:.0f} f1={result['f1']:.2f} "
                f"{'cached' if cached else str(result['seconds']) + 's'}",
                flush=True,
            )


# --- comparison ---------------------------------------------------------------------------


def paired(a: dict[str, dict], b: dict[str, dict], qids: list[str], metric: str) -> dict:
    xs = [a[q][metric] for q in qids]
    ys = [b[q][metric] for q in qids]
    diffs = [y - x for x, y in zip(xs, ys, strict=True)]
    wins = sum(d > 0 for d in diffs)
    losses = sum(d < 0 for d in diffs)
    lo, hi = bootstrap_ci(diffs) if diffs else (0.0, 0.0)
    n = len(qids) or 1
    return {
        "a": round(100 * sum(xs) / n, 2),
        "b": round(100 * sum(ys) / n, 2),
        "diff": round(100 * sum(diffs) / n, 2),
        "ci95": [round(100 * lo, 2), round(100 * hi, 2)],
        "wins": wins,
        "losses": losses,
        "sign_p": round(sign_test(wins, losses), 4),
    }


def compare(rows_a: list[dict], rows_b: list[dict], groups: dict[str, str] | None = None) -> dict:
    a = {r["qid"]: r for r in rows_a}
    b = {r["qid"]: r for r in rows_b}
    qids = [q for q in a if q in b]
    out: dict = {"questions": len(qids)}
    out["same_top"] = sum(a[q]["top"] == b[q]["top"] for q in qids if "top" in a[q])
    for metric in ("f1", "em"):
        out[metric] = paired(a, b, qids, metric)
    if groups:
        for name in sorted({groups[q] for q in qids if q in groups}):
            sub = [q for q in qids if groups.get(q) == name]
            out[f"group={name}"] = {
                "questions": len(sub),
                **{m: paired(a, b, sub, m) for m in ("f1", "em")},
            }
    return out


def manifest_groups(path: Path) -> dict[str, str]:
    """qid -> ``type`` (2Wiki) or ``<n>hop`` (MuSiQue)."""
    out = {}
    for row in _load_jsonl(path):
        out[row["qid"]] = row.get("type") or f"{row.get('hop_count', len(row['hops']))}hop"
    return out


def export(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for r in rows:
            compact = {"qid": r["qid"], "answer": r["answer"], "em": r["em"], "f1": r["f1"]}
            handle.write(json.dumps(compact, ensure_ascii=False) + "\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("read")
    p.add_argument("--run", type=Path, required=True, help="pipeline_probe output (--keep-top)")
    p.add_argument("--manifest", type=Path, required=True, help="for the question text")
    p.add_argument("--dataset", type=Path, required=True, help="HippoRAG <dataset>.json")
    p.add_argument("--corpus", type=Path, required=True, help="HippoRAG <dataset>_corpus.json")
    p.add_argument("--label-prefix", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--prompt-cache", type=Path)
    p.add_argument("--host", default="http://localhost:11434")
    p.add_argument("--model", default="qwen2.5:3b")
    p.add_argument("--expect-digest", help="prefix of the Ollama model digest")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--num-predict", type=int, default=256)
    p.add_argument("--limit", type=int, default=0)

    p = sub.add_parser("compare")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)
    p.add_argument("--manifest", type=Path, help="group by hop count / 2Wiki type")
    p.add_argument("--limit", type=int, default=0, help="first N questions of A only")

    p = sub.add_parser("export")
    p.add_argument("answers", type=Path)
    p.add_argument("output", type=Path)

    args = parser.parse_args()
    if args.cmd == "read":
        questions = {r["qid"]: r["question"] for r in _load_jsonl(args.manifest)}
        args.question_of = questions.__getitem__
        read(args)
    elif args.cmd == "compare":
        rows_a = _load_jsonl(args.a)
        if args.limit:
            rows_a = rows_a[: args.limit]
        groups = manifest_groups(args.manifest) if args.manifest else None
        print(json.dumps(compare(rows_a, _load_jsonl(args.b), groups), indent=2))
    else:
        export(_load_jsonl(args.answers), args.output)


if __name__ == "__main__":
    main()
