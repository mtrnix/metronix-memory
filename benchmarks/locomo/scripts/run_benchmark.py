#!/usr/bin/env python3
"""Run the official LoCoMo QA dataset against Metronix memory."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import backoff
import openai
from openai import OpenAI
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BENCH_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks._shared import manifest as run_manifest  # noqa: E402
from benchmarks._shared import oracle, retrieval_eval  # noqa: E402
from benchmarks.locomo.scripts.dataset import (  # noqa: E402
    DATASET_PATH,
    DATASET_SHA256,
    DATASET_URL,
    UPSTREAM_COMMIT,
    dataset_summary,
    download_dataset,
    iter_questions,
    load_dataset,
)
from benchmarks.locomo.scripts.env_config import BenchConfig  # noqa: E402
from benchmarks.longmemeval.scripts.metronix_client import MetronixMCPClient  # noqa: E402

logger = logging.getLogger(__name__)
RESULTS_DIR = BENCH_ROOT / "results"

ANSWER_SYSTEM = (
    "Answer the question using only the retrieved memories. Be concise and factual. "
    "If the answer is absent, reply exactly: No information available."
)
ANSWER_PROMPT = """Retrieved memories:\n{memory_context}\n\nQuestion: {question}\nAnswer:"""


class EmptyChatCompletionError(ValueError):
    """A provider returned a completion without answer content."""

    def __init__(self, finish_reason: str) -> None:
        self.finish_reason = finish_reason
        super().__init__(f"chat model returned an empty answer (finish_reason={finish_reason})")


def parse_categories(value: str) -> set[int]:
    try:
        categories = {int(item.strip()) for item in value.split(",") if item.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("categories must be comma-separated integers") from exc
    if not categories or not categories.issubset({1, 2, 3, 4, 5}):
        raise argparse.ArgumentTypeError("categories must be selected from 1,2,3,4,5")
    return categories


def format_session_text(turns: list[dict], date: str = "") -> str:
    lines = [f"[Conversation date: {date}]"] if date else []
    for turn in turns:
        text = turn.get("text") or turn.get("blip_caption") or ""
        lines.append(f"{turn.get('speaker', 'Unknown')}: {text}")
    return "\n".join(lines)


def build_memory_context(results: list[dict]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(results, start=1):
        record = item.get("record", {}) if isinstance(item, dict) else {}
        blocks.append(f"[Memory {index}]\n{record.get('content', '')}")
    return "\n\n".join(blocks) if blocks else "(no memories retrieved)"


CHAT_TEMPERATURE = 0.0
CHAT_MAX_TOKENS = 512


@backoff.on_exception(
    backoff.expo,
    (openai.RateLimitError, openai.APIError, EmptyChatCompletionError),
    max_tries=8,
)
def chat_complete(client: OpenAI, *, model: str, message: str) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": message},
        ],
        temperature=CHAT_TEMPERATURE,
        max_tokens=CHAT_MAX_TOKENS,
    )
    content = completion.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        finish_reason = str(completion.choices[0].finish_reason or "unknown")
        raise EmptyChatCompletionError(finish_reason)
    return content.strip()


def load_completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {
        json.loads(line)["question_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def append_result(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def process_question(entry: dict, *, config: BenchConfig, chat_client: OpenAI) -> tuple[str, dict]:
    client = MetronixMCPClient(
        mcp_url=config.metronix_mcp_url,
        api_key=config.metronix_mcp_api_key,
        workspace_id=config.workspace_id,
        agent_id=f"{config.agent_id_prefix}-{entry['question_id']}",
        source_type="locomo",
    )
    # Search deep enough for recall@10 even when the answer prompt uses a
    # smaller top_k; only ``retrieve_top_k`` hits reach the LLM.
    search_k = max(config.retrieve_top_k, retrieval_eval.SEARCH_K_FLOOR)
    results = client.ingest_and_search(
        sessions=entry["sessions"],
        dates=entry["dates"],
        format_session_text=format_session_text,
        query=entry["question"],
        top_k=search_k,
    )
    answer_hits = results[: config.retrieve_top_k]
    prompt = ANSWER_PROMPT.format(
        memory_context=build_memory_context(answer_hits), question=entry["question"]
    )
    hypothesis = chat_complete(chat_client, model=config.chat_model, message=prompt)

    retrieval = retrieval_eval.recall_row(
        oracle.locomo_oracle_tags(entry),
        oracle.retrieved_session_tags(results),
        eligible=not oracle.locomo_is_abstention(entry),
    )
    retrieval["retrieved_count"] = len(answer_hits)
    return hypothesis, retrieval


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return RESULTS_DIR / f"{timestamp}.jsonl"


def build_run_artifacts(
    *,
    config: BenchConfig,
    categories: set[int],
    retrieval_mode: str,
    entries: Sequence[dict],
    run_id: str | None = None,
) -> tuple[dict, dict]:
    """Return ``(manifest, query_set)`` for the exact question set to be run."""
    ids = [entry["question_id"] for entry in entries]
    query_set = run_manifest.build_query_set(
        benchmark="locomo",
        selector={"categories": sorted(categories)},
        question_ids=ids,
    )
    manifest = run_manifest.build_manifest(
        benchmark="locomo",
        repo_root=REPO_ROOT,
        run_id=run_id,
        dataset={
            "name": "locomo10",
            "source_url": DATASET_URL,
            "upstream_ref": UPSTREAM_COMMIT,
            "sha256": DATASET_SHA256,
            "question_count": len(ids),
        },
        query_set=query_set,
        config={
            "workspace": config.workspace_id,
            "top_k": config.retrieve_top_k,
            "agent_id_prefix": config.agent_id_prefix,
            "chat_model": config.chat_model,
            "chat_base_url": config.chat_base_url,
            "chat_temperature": CHAT_TEMPERATURE,
            "chat_max_tokens": CHAT_MAX_TOKENS,
            "categories": sorted(categories),
        },
        stack={
            "mcp_endpoint_identity": run_manifest.sanitized_endpoint_identity(
                config.metronix_mcp_url
            ),
            "operator_declared_retrieval_mode": retrieval_mode,
        },
        metrics_requested=["recall_at_10", "recall_at_5", "answer_token_f1"],
    )
    return manifest, query_set


def write_manifest(
    path: Path,
    *,
    config: BenchConfig,
    categories: set[int],
    retrieval_mode: str,
    dataset_path: Path,  # noqa: ARG001 — kept for call-site compatibility; sha comes from dataset.py
    entries: Sequence[dict] = (),
) -> Path:
    """Write ``<path>.manifest.json`` and ``<path>.query_set.json``; return the manifest path."""
    manifest, query_set = build_run_artifacts(
        config=config,
        categories=categories,
        retrieval_mode=retrieval_mode,
        entries=entries,
    )
    manifest_path, _ = run_manifest.write_run_artifacts(
        path, manifest=manifest, query_set=query_set
    )
    return manifest_path


def run(
    *,
    config: BenchConfig,
    dataset_path: Path,
    output_path: Path,
    categories: set[int],
    max_questions: int | None,
    force: bool,
    retrieval_mode: str,
) -> Path:
    config = replace(config, agent_id_prefix=f"locomo-{retrieval_mode}")
    dataset = load_dataset(dataset_path)
    entries = list(iter_questions(dataset, categories=categories))
    if max_questions is not None:
        entries = entries[:max_questions]
    if force:
        output_path.unlink(missing_ok=True)
    write_manifest(
        output_path,
        config=config,
        categories=categories,
        retrieval_mode=retrieval_mode,
        dataset_path=dataset_path,
        entries=entries,
    )
    done = load_completed_ids(output_path)
    remaining = [entry for entry in entries if entry["question_id"] not in done]
    client = OpenAI(api_key=config.chat_api_key, base_url=config.chat_base_url)
    for entry in tqdm(remaining, desc="LoCoMo", unit="q"):
        started = time.perf_counter()
        retrieval: dict = {"retrieved_count": 0}
        error: dict[str, str] | None = None
        try:
            hypothesis, retrieval = process_question(entry, config=config, chat_client=client)
        except Exception as exc:  # keep resumable artifacts after isolated failures
            logger.error("Error on %s: %s", entry["question_id"], exc)
            traceback.print_exc()
            hypothesis = f"Error: {type(exc).__name__}"
            if isinstance(exc, EmptyChatCompletionError):
                error = {
                    "type": "empty_chat_completion",
                    "finish_reason": exc.finish_reason,
                }
        row = {
            "question_id": entry["question_id"],
            "sample_id": entry["sample_id"],
            "category": entry["category"],
            "question": entry["question"],
            "answer": entry["answer"],
            "evidence": entry["evidence"],
            "hypothesis": hypothesis,
            "latency_ms": (time.perf_counter() - started) * 1000,
            **retrieval,
        }
        if error is not None:
            row["error"] = error
        append_result(output_path, row)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LoCoMo benchmark runner for Metronix")
    subparsers = parser.add_subparsers(dest="command", required=True)
    download = subparsers.add_parser("download")
    download.add_argument("--force", action="store_true")
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--dataset", type=Path, default=DATASET_PATH)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--categories", type=parse_categories, default={1, 2, 3, 4})
    run_parser.add_argument("--max-questions", type=int)
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument(
        "--retrieval-mode",
        choices=("flag-off", "flag-on"),
        required=True,
        help="Operator-confirmed server mode; restart Metronix with the matching PPR flag",
    )
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args()
    if args.command == "download":
        path = download_dataset(DATASET_PATH, force=args.force)
        print(f"Dataset: {path}\nSHA-256: {DATASET_SHA256}\nUpstream: {DATASET_URL}")
        return 0
    if args.command == "inspect":
        print(json.dumps(dataset_summary(load_dataset(args.dataset)), indent=2, sort_keys=True))
        print(f"upstream_commit: {UPSTREAM_COMMIT}\nsha256: {DATASET_SHA256}")
        return 0
    config = BenchConfig.from_env()
    if missing := config.missing():
        print("ERROR: missing required configuration: " + ", ".join(missing))
        return 2
    output = args.output or default_output_path()
    run(
        config=config,
        dataset_path=args.dataset,
        output_path=output,
        categories=args.categories,
        max_questions=args.max_questions,
        force=args.force,
        retrieval_mode=args.retrieval_mode,
    )
    print(f"Results: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
