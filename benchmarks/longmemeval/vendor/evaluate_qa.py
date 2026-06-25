"""LongMemEval QA evaluation with an OpenAI-compatible LLM judge.

Adapted from https://github.com/xiaowu0162/LongMemEval (ICLR 2025).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import backoff
import numpy as np
import openai
from openai import OpenAI
from tqdm import tqdm


def get_anscheck_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    *,
    abstention: bool = False,
) -> str:
    if not abstention:
        if task in ["single-session-user", "single-session-assistant", "multi-session"]:
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, "
                "answer no. If the response is equivalent to the correct answer or contains "
                "all the intermediate steps to get the correct answer, you should also answer "
                "yes. If the response only contains a subset of the information required by "
                "the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\n"
                "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)
        if task == "temporal-reasoning":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, "
                "answer no. If the response is equivalent to the correct answer or contains "
                "all the intermediate steps to get the correct answer, you should also answer "
                "yes. If the response only contains a subset of the information required by "
                "the answer, answer no. In addition, do not penalize off-by-one errors for "
                "the number of days. If the question asks for the number of days/weeks/months, "
                "etc., and the model makes off-by-one errors (e.g., predicting 19 days when "
                "the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\n"
                "Correct Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)
        if task == "knowledge-update":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, "
                "answer no. If the response contains some previous information along with an "
                "updated answer, the response should be considered as correct as long as the "
                "updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\n"
                "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)
        if task == "single-session-preference":
            template = (
                "I will give you a question, a rubric for desired personalized response, "
                "and a response from a model. Please answer yes if the response satisfies "
                "the desired response. Otherwise, answer no. The model does not need to reflect "
                "all the points in the rubric. The response is correct as long as it recalls "
                "and utilizes the user's personal information correctly.\n\nQuestion: {}\n\n"
                "Rubric: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)
        raise NotImplementedError(f"Unsupported task type: {task}")

    template = (
        "I will give you an unanswerable question, an explanation, and a response from a model. "
        "Please answer yes if the model correctly identifies the question as unanswerable. "
        "The model could say that the information is incomplete, or some other information is "
        "given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\n"
        "Model Response: {}\n\nDoes the model correctly identify the question as unanswerable? "
        "Answer yes or no only."
    )
    return template.format(question, answer, response)


@backoff.on_exception(backoff.expo, (openai.RateLimitError, openai.APIError), max_tries=8)
def chat_completions_with_backoff(client: OpenAI, **kwargs):
    return client.chat.completions.create(**kwargs)


def extract_judge_text(message: object) -> str:
    """Return judge output text, including reasoning-model fallback fields."""
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content

    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        return str(reasoning).strip()

    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
        for key in ("content", "reasoning_content", "reasoning"):
            value = data.get(key)
            if value:
                return str(value).strip()
    return ""


def parse_judge_label(text: str) -> bool:
    """Parse LongMemEval yes/no judge output."""
    if not text:
        return False
    normalized = text.lower().strip()
    first_token = normalized.split()[0] if normalized.split() else ""
    if first_token.startswith("yes"):
        return True
    if first_token.startswith("no"):
        return False
    last_line = normalized.splitlines()[-1].strip()
    if last_line.startswith("yes"):
        return True
    if last_line.startswith("no"):
        return False
    return "yes" in normalized


def load_json_or_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        raw = handle.read().strip()
    if not raw:
        return []
    if raw.startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def evaluate(
    *,
    results_path: str,
    reference_path: str,
    judge_model: str,
    judge_base_url: str,
    judge_api_key: str,
    verbose: bool = True,
) -> str:
    metric_client = OpenAI(api_key=judge_api_key, base_url=judge_base_url)
    result_file = f"{results_path}.eval-{judge_model.replace('/', '_')}"

    hypotheses = load_json_or_jsonl(results_path)
    references = load_json_or_jsonl(reference_path)
    qid2qdata = {entry["question_id"]: entry for entry in references}
    qid2qtype = {entry["question_id"]: entry["question_type"] for entry in references}
    qtypes = set(qid2qtype.values())
    qtype2acc: dict[str, list[int]] = {task: [] for task in qtypes}
    logs: list[dict] = []

    for entry in tqdm(hypotheses, desc="Evaluating"):
        if entry["question_id"] not in qid2qtype:
            print(f"Warning: skipping {entry['question_id']} — not in reference data.")
            continue

        qtype = qid2qtype[entry["question_id"]]
        question = qid2qdata[entry["question_id"]]["question"]
        answer = qid2qdata[entry["question_id"]]["answer"]
        hyp = entry["hypothesis"]

        prompt = get_anscheck_prompt(
            qtype,
            question,
            answer,
            hyp,
            abstention="_abs" in entry["question_id"],
        )
        completion = chat_completions_with_backoff(
            metric_client,
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            n=1,
            temperature=0,
            max_tokens=256,
        )
        message = completion.choices[0].message
        eval_response = extract_judge_text(message)
        label = parse_judge_label(eval_response)
        entry["autoeval_label"] = {
            "model": judge_model,
            "label": label,
            "raw_response": eval_response,
        }
        logs.append(entry)
        qtype2acc[qtype].append(1 if label else 0)

        if verbose:
            print(
                json.dumps(
                    {
                        "question": question,
                        "answer": answer,
                        "hypothesis": hyp,
                        "autoeval_label": label,
                        "judge_raw_response": eval_response,
                    },
                    indent=2,
                ),
                flush=True,
            )

    with open(result_file, "w", encoding="utf-8") as out_f:
        for entry in logs:
            out_f.write(json.dumps(entry) + "\n")

    overall = round(np.mean([1 if x["autoeval_label"]["label"] else 0 for x in logs]).item(), 4)
    print("Accuracy:", overall)
    for task, values in qtype2acc.items():
        if values:
            print(f"\t{task}: {round(np.mean(values), 4)} ({len(values)})")
    print("Saved to", result_file)
    return result_file


def main() -> int:
    parser = argparse.ArgumentParser(description="LongMemEval LLM judge evaluation")
    parser.add_argument("--results", required=True, help="Hypothesis JSONL file")
    parser.add_argument("--reference", required=True, help="Reference dataset JSON file")
    parser.add_argument("--judge-model", default=os.getenv("LME_JUDGE_MODEL", "gpt-4o"))
    parser.add_argument(
        "--judge-base-url",
        default=os.getenv("LME_JUDGE_BASE_URL", "https://api.openai.com/v1"),
    )
    parser.add_argument(
        "--judge-api-key",
        default=os.getenv("LME_JUDGE_API_KEY")
        or os.getenv("LME_CHAT_API_KEY")
        or os.getenv("OPENAI_API_KEY"),
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-question output")
    args = parser.parse_args()

    if not args.judge_api_key:
        print("ERROR: judge API key required (--judge-api-key or LME_JUDGE_API_KEY)")
        return 1

    evaluate(
        results_path=args.results,
        reference_path=args.reference,
        judge_model=args.judge_model,
        judge_base_url=args.judge_base_url,
        judge_api_key=args.judge_api_key,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
