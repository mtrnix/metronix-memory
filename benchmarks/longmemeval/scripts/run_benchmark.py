#!/usr/bin/env python3
"""LongMemEval-S benchmark harness for Metronix agent memory."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import backoff
import openai
from openai import OpenAI
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BENCH_ROOT.parents[1]
for _path in (SCRIPT_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import dataset as lme_dataset  # noqa: E402
from env_config import BenchConfig, load_dotenv  # noqa: E402
from metronix_client import MetronixMCPClient  # noqa: E402

from benchmarks._shared import manifest as run_manifest  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = lme_dataset.DATA_DIR
RESULTS_DIR = BENCH_ROOT / "results"
DATASET_FILENAMES = {name: spec["filename"] for name, spec in lme_dataset.VARIANTS.items()}
DATASET_VARIANTS = lme_dataset.VARIANT_NAMES

ANSWER_SYSTEM = (
    "You are a helpful chat assistant. You have access to memories retrieved "
    "from your past conversations with the user. Use these memories to answer "
    "the user's question. If the memories do not contain enough information, "
    "say so honestly."
)

ANSWER_PROMPT = """\
Below are memories retrieved from our past conversations, followed by the \
user's question.

Important guidelines:
- Each conversation is tagged with its date in a [Conversation date: ...] \
header. Use these dates to reason about when events happened, their \
chronological order, and time spans between them.
- When information was updated across conversations (e.g., a number changed, \
a preference shifted, a status was revised), ALWAYS use the value from the \
MOST RECENT conversation. Later conversations supersede earlier ones.
- Answer based only on what is explicitly stated. Do not add to or modify \
stated values (e.g., if the user says "my list has 25 titles", the answer \
is 25 — do not add items mentioned in the same conversation unless the user \
explicitly said the count changed).
- If the question asks for a recommendation or suggestion, USE the \
preferences and details you find in the memories to give a SPECIFIC, \
CONCRETE answer. Do NOT ask clarifying questions back to the user — they \
already shared their preferences in past conversations, and your job is to \
remember and apply them.
- Tailor your response to the user's specific interests, hobbies, or domain \
mentioned in the memories. Generic answers that ignore the user's known \
preferences are wrong.
- For counting questions ("how many X"), carefully enumerate every distinct \
item mentioned across ALL conversations. Do not skip items because they \
appear in different sessions. Build a numbered list first, then count.

## Retrieved Memories
{memory_context}

## Current Date
{current_date}

## Question
{question}

Answer the question step by step:
1. Extract ALL relevant facts, preferences, and dates from the memories above.
2. If the question involves timing or ordering, note the conversation dates.
3. If the same fact appears with different values across conversations, use \
the value from the latest conversation date.
4. If the question asks for a recommendation, immediately apply the user's \
known preferences to produce a specific answer — do not ask the user to \
restate them.
5. Give a direct, specific answer — do not say "I don't know" unless the \
information is truly absent from the memories."""


def download_datasets(variants: list[str] | None = None, *, force: bool = False) -> None:
    for variant in variants or list(lme_dataset.VARIANT_NAMES):
        path = lme_dataset.download_dataset(variant, force=force)
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  {path.name} ready ({size_mb:.1f} MB), sha256 verified")


def load_dataset(variant: str) -> list[dict]:
    """Load the pinned dataset, verifying its SHA-256 first (see ``dataset.py``)."""
    return lme_dataset.load_dataset(variant)


def format_session_text(session: list[dict], date: str = "") -> str:
    lines: list[str] = []
    if date:
        lines.append(f"[Conversation date: {date}]")
    for turn in session:
        role = turn["role"].capitalize()
        lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


def build_memory_context(search_results: list[dict]) -> str:
    if not search_results:
        return "(no memories retrieved)"
    blocks: list[str] = []
    for idx, item in enumerate(search_results, start=1):
        record = item.get("record", {})
        content = record.get("content", "")
        score = item.get("score")
        header = f"[Memory {idx}]"
        if score is not None:
            header += f" (score={score:.3f})"
        blocks.append(f"{header}\n{content}")
    return "\n\n".join(blocks)


def load_completed_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            done.add(json.loads(line)["question_id"])
    return done


def append_result(path: Path, question_id: str, hypothesis: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"question_id": question_id, "hypothesis": hypothesis}) + "\n")


CHAT_TEMPERATURE = 0.0
CHAT_MAX_TOKENS = 1024


@backoff.on_exception(backoff.expo, (openai.RateLimitError, openai.APIError), max_tries=8)
def chat_complete(client: OpenAI, *, model: str, user_message: str) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        temperature=CHAT_TEMPERATURE,
        max_tokens=CHAT_MAX_TOKENS,
    )
    return completion.choices[0].message.content.strip()


def process_question(
    entry: dict,
    *,
    config: BenchConfig,
    chat_client: OpenAI,
) -> str:
    question_id = entry["question_id"]
    agent_id = f"{config.agent_id_prefix}-{question_id}"
    mcp_client = MetronixMCPClient(
        mcp_url=config.metronix_mcp_url,
        api_key=config.metronix_mcp_api_key,
        workspace_id=config.workspace_id,
        agent_id=agent_id,
    )

    sessions = entry["haystack_sessions"]
    dates = entry["haystack_dates"]
    question = entry["question"]
    current_date = entry.get("question_date", "")

    search_results = mcp_client.ingest_and_search(
        sessions=sessions,
        dates=dates,
        format_session_text=format_session_text,
        query=question,
        top_k=config.retrieve_top_k,
    )
    memory_context = build_memory_context(search_results)

    user_message = ANSWER_PROMPT.format(
        memory_context=memory_context,
        current_date=current_date,
        question=question,
    )
    return chat_complete(chat_client, model=config.chat_model, user_message=user_message)


def default_output_path(variant: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return RESULTS_DIR / f"{timestamp}_{variant}.jsonl"


def build_run_artifacts(
    *,
    variant: str,
    entries: list[dict],
    config: BenchConfig,
    max_questions: int | None,
    retrieval_mode: str,
    run_id: str | None = None,
) -> tuple[dict, dict]:
    """Return ``(manifest, query_set)`` for the exact question set to be run."""
    ids = [entry["question_id"] for entry in entries]
    query_set = run_manifest.build_query_set(
        benchmark="longmemeval",
        selector={"variant": variant, "max_questions": max_questions},
        question_ids=ids,
    )
    manifest = run_manifest.build_manifest(
        benchmark="longmemeval",
        repo_root=REPO_ROOT,
        run_id=run_id,
        dataset=lme_dataset.dataset_identity(variant, question_count=len(ids)),
        query_set=query_set,
        config={
            "workspace": config.workspace_id,
            "top_k": config.retrieve_top_k,
            "agent_id_prefix": config.agent_id_prefix,
            "chat_model": config.chat_model,
            "chat_base_url": config.chat_base_url,
            "chat_temperature": CHAT_TEMPERATURE,
            "chat_max_tokens": CHAT_MAX_TOKENS,
            "judge_model": config.judge_model,
            "judge_base_url": config.judge_base_url,
        },
        stack={
            "mcp_endpoint_identity": run_manifest.sanitized_endpoint_identity(
                config.metronix_mcp_url
            ),
            "operator_declared_retrieval_mode": retrieval_mode,
        },
        metrics_requested=["answer_accuracy"],
    )
    return manifest, query_set


def run_benchmark(
    *,
    variant: str,
    output_path: Path,
    config: BenchConfig,
    max_questions: int | None = None,
    resume: bool = True,
    force: bool = False,
    retrieval_mode: str = "unspecified",
) -> Path:
    dataset = load_dataset(variant)
    entries = lme_dataset.select_questions(dataset, max_questions=max_questions)

    if force and output_path.exists():
        output_path.unlink()

    manifest, query_set = build_run_artifacts(
        variant=variant,
        entries=entries,
        config=config,
        max_questions=max_questions,
        retrieval_mode=retrieval_mode,
    )
    m_path, q_path = run_manifest.write_run_artifacts(
        output_path, manifest=manifest, query_set=query_set
    )
    print(f"  MANIFEST: {m_path}")
    print(f"  QUERY SET: {q_path} ({query_set['question_ids_sha256'][:12]}…)")

    done_ids = load_completed_ids(output_path) if resume else set()
    remaining = [entry for entry in entries if entry["question_id"] not in done_ids]
    if not remaining:
        print("All questions already completed.")
        return output_path

    chat_client = OpenAI(api_key=config.chat_api_key, base_url=config.chat_base_url)

    print()
    print("=" * 60)
    print(f"  CHAT MODEL: {config.chat_model}")
    print(f"  CHAT BASE URL: {config.chat_base_url}")
    print(f"  WORKSPACE: {config.workspace_id}")
    print(f"  QUESTIONS: {len(remaining)} (of {len(entries)} after resume)")
    print(f"  OUTPUT: {output_path}")
    print("=" * 60)

    for entry in tqdm(remaining, desc="LongMemEval", unit="q"):
        qid = entry["question_id"]
        try:
            hypothesis = process_question(entry, config=config, chat_client=chat_client)
        except Exception as exc:
            logger.error("Error on %s: %s", qid, exc)
            traceback.print_exc()
            hypothesis = f"Error: {exc}"
        append_result(output_path, qid, hypothesis)

    total = len(load_completed_ids(output_path))
    print(f"\nDone. {total} answers written to {output_path}")
    return output_path


def cmd_download(args: argparse.Namespace) -> int:
    variants = [args.variant] if args.variant else list(DATASET_VARIANTS)
    print(f"Downloading LongMemEval datasets (pinned @ {lme_dataset.HF_REVISION[:12]}) ...")
    download_datasets(variants, force=args.force)
    print("Download complete.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv()
    config = BenchConfig.from_env(load_files=False).apply_cli_overrides(
        chat_api_key=args.chat_api_key,
        chat_base_url=args.chat_base_url,
        chat_model=args.chat_model,
        workspace_id=args.workspace,
        retrieve_top_k=args.top_k,
    )
    if not config.metronix_mcp_api_key:
        print("ERROR: METRONIX_MCP_API_KEY is required")
        return 1
    if not config.chat_api_key:
        print("ERROR: LME_CHAT_API_KEY (or OPENAI_API_KEY) is required")
        return 1

    output_path = Path(args.output) if args.output else default_output_path(args.variant)
    run_benchmark(
        variant=args.variant,
        output_path=output_path,
        config=config,
        max_questions=args.max_questions,
        resume=not args.no_resume,
        force=args.force,
        retrieval_mode=args.declare_retrieval_mode,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LongMemEval benchmark runner for Metronix")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download dataset files")
    download_parser.add_argument(
        "--variant",
        choices=list(DATASET_VARIANTS),
        default="s",
        help="Dataset variant to download",
    )
    download_parser.add_argument(
        "--force", action="store_true", help="Re-download even if the file exists"
    )
    download_parser.set_defaults(func=cmd_download)

    run_parser = subparsers.add_parser("run", help="Run benchmark generation")
    run_parser.add_argument("--variant", choices=list(DATASET_VARIANTS), default="s")
    run_parser.add_argument("--output", help="Output JSONL path")
    run_parser.add_argument("--max-questions", type=int, help="Limit number of questions")
    run_parser.add_argument("--workspace", help="Metronix workspace ID")
    run_parser.add_argument("--top-k", type=int, help="Memory search top_k")
    run_parser.add_argument("--chat-api-key", help="Override LME_CHAT_API_KEY")
    run_parser.add_argument("--chat-base-url", help="Override LME_CHAT_BASE_URL")
    run_parser.add_argument("--chat-model", help="Override LME_CHAT_MODEL")
    run_parser.add_argument("--no-resume", action="store_true", help="Do not skip completed IDs")
    run_parser.add_argument(
        "--force", action="store_true", help="Delete existing output before run"
    )
    run_parser.add_argument(
        "--declare-retrieval-mode",
        default="unspecified",
        help="Operator-confirmed server retrieval mode, recorded in the run manifest "
        "(e.g. flag-off / flag-on for a PPR A/B)",
    )
    run_parser.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
