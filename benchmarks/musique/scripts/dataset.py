"""MuSiQue-Ans dev split download, validation, and 2-hop slicing."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

HF_REPO_ID = "dgslibisey/MuSiQue"
TWO_HOP_PREFIX = "2hop__"


def _to_py(value: Any) -> Any:
    """Convert numpy/pyarrow containers (parquet rows) into plain Python values."""
    if hasattr(value, "tolist") and not isinstance(value, str | bytes):
        value = value.tolist()
    if isinstance(value, dict):
        return {k: _to_py(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_py(v) for v in value]
    return value


def validate_record(record: dict) -> dict:
    qid = record.get("id")
    if not isinstance(qid, str) or not qid:
        raise ValueError("MuSiQue record has no id")
    paragraphs = record.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError(f"MuSiQue record {qid} has no paragraphs")
    for para in paragraphs:
        if not {"idx", "title", "paragraph_text", "is_supporting"} <= set(para):
            raise ValueError(f"MuSiQue record {qid} has a malformed paragraph")
    steps = record.get("question_decomposition")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"MuSiQue record {qid} has no question_decomposition")
    for step in steps:
        if not {"question", "answer", "paragraph_support_idx"} <= set(step):
            raise ValueError(f"MuSiQue record {qid} has a malformed decomposition step")
    return record


def load_records(path: Path) -> list[dict]:
    """Load MuSiQue records from a .jsonl or .parquet file."""
    if path.suffix == ".parquet":
        import pandas as pd

        rows = pd.read_parquet(path).to_dict(orient="records")
    else:
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    return [validate_record(_to_py(row)) for row in rows]


def iter_two_hop(records: Iterable[dict], answerable_only: bool = True) -> Iterator[dict]:
    for record in records:
        if not record["id"].startswith(TWO_HOP_PREFIX):
            continue
        if answerable_only and record.get("answerable") is False:
            continue
        if len(record["question_decomposition"]) != 2:
            continue
        yield record


def select_two_hop(records: Iterable[dict], limit: int) -> list[dict]:
    """First ``limit`` answerable 2-hop questions, in file order (deterministic)."""
    selected: list[dict] = []
    for record in iter_two_hop(records):
        selected.append(record)
        if len(selected) >= limit:
            break
    return selected


def write_jsonl(records: Iterable[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def find_dev_file(repo_files: Iterable[str]) -> str:
    """Pick the MuSiQue-Ans dev/validation file from a HF dataset repo listing."""
    candidates = [
        f
        for f in repo_files
        if f.endswith((".jsonl", ".parquet"))
        and ("dev" in f.lower() or "validation" in f.lower())
        and "full" not in f.lower()
    ]
    if not candidates:
        raise ValueError(f"no MuSiQue-Ans dev file found in {HF_REPO_ID}")
    # Prefer the explicit "ans" jsonl when both formats are present.
    candidates.sort(key=lambda f: ("ans" not in f.lower(), not f.endswith(".jsonl"), f))
    return candidates[0]


def download_dev(cache_dir: Path) -> Path:
    from huggingface_hub import hf_hub_download, list_repo_files

    filename = find_dev_file(list_repo_files(HF_REPO_ID, repo_type="dataset"))
    return Path(
        hf_hub_download(HF_REPO_ID, filename, repo_type="dataset", cache_dir=str(cache_dir))
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download MuSiQue-Ans dev and slice 2-hop")
    parser.add_argument("--input", type=Path, help="local dev file; skips the download")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/musique/data/dev_2hop.jsonl")
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("benchmarks/musique/data/.hf"))
    args = parser.parse_args()

    source = args.input or download_dev(args.cache_dir)
    written = write_jsonl(select_two_hop(load_records(source), args.limit), args.output)
    print(f"wrote {written} 2-hop questions from {source} to {args.output}")


if __name__ == "__main__":
    main()
