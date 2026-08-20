#!/usr/bin/env python3
"""Run the official LoCoMo QA dataset against Metronix memory."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import traceback
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

from benchmarks.locomo.scripts.dataset import (  # noqa: E402
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
DATASET_PATH = BENCH_ROOT / "data" / "locomo10.json"
RESULTS_DIR = BENCH_ROOT / "results"

ANSWER_SYSTEM = (
    "Answer the question using only the retrieved memories. Be concise and factual. "
    "If the answer is absent, reply exactly: No information available."
)
ANSWER_PROMPT = """Retrieved memories:\n{memory_context}\n\nQuestion: {question}\nAnswer:"""


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


@backoff.on_exception(backoff.expo, (openai.RateLimitError, openai.APIError), max_tries=8)
def chat_complete(client: OpenAI, *, model: str, message: str) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": message},
        ],
        temperature=0.0,
        max_tokens=512,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ValueError("chat model returned an empty answer")
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


def process_question(entry: dict, *, config: BenchConfig, chat_client: OpenAI) -> tuple[str, int]:
    client = MetronixMCPClient(
        mcp_url=config.metronix_mcp_url,
        api_key=config.metronix_mcp_api_key,
        workspace_id=config.workspace_id,
        agent_id=f"{config.agent_id_prefix}-{entry['question_id']}",
        source_type="locomo",
    )
    results = client.ingest_and_search(
        sessions=entry["sessions"],
        dates=entry["dates"],
        format_session_text=format_session_text,
        query=entry["question"],
        top_k=config.retrieve_top_k,
    )
    prompt = ANSWER_PROMPT.format(
        memory_context=build_memory_context(results), question=entry["question"]
    )
    return chat_complete(chat_client, model=config.chat_model, message=prompt), len(results)


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return RESULTS_DIR / f"{timestamp}.jsonl"


def write_manifest(
    path: Path,
    *,
    config: BenchConfig,
    categories: set[int],
    retrieval_mode: str,
    dataset_path: Path,
) -> Path:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark": "locomo",
                "repository_revision": revision,
                "operator_declared_retrieval_mode": retrieval_mode,
                "workspace": config.workspace_id,
                "top_k": config.retrieve_top_k,
                "chat_model": config.chat_model,
                "chat_base_url": config.chat_base_url,
                "categories": sorted(categories),
                "dataset": {
                    "path": str(dataset_path),
                    "upstream_commit": UPSTREAM_COMMIT,
                    "sha256": DATASET_SHA256,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
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
    )
    done = load_completed_ids(output_path)
    remaining = [entry for entry in entries if entry["question_id"] not in done]
    client = OpenAI(api_key=config.chat_api_key, base_url=config.chat_base_url)
    for entry in tqdm(remaining, desc="LoCoMo", unit="q"):
        started = time.perf_counter()
        retrieved_count = 0
        try:
            hypothesis, retrieved_count = process_question(
                entry, config=config, chat_client=client
            )
        except Exception as exc:  # keep resumable artifacts after isolated failures
            logger.error("Error on %s: %s", entry["question_id"], exc)
            traceback.print_exc()
            hypothesis = f"Error: {type(exc).__name__}"
        append_result(
            output_path,
            {
                "question_id": entry["question_id"],
                "sample_id": entry["sample_id"],
                "category": entry["category"],
                "question": entry["question"],
                "answer": entry["answer"],
                "evidence": entry["evidence"],
                "hypothesis": hypothesis,
                "retrieved_count": retrieved_count,
                "latency_ms": (time.perf_counter() - started) * 1000,
            },
        )
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
