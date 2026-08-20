"""Pinned LoCoMo dataset download, validation, and normalization."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

UPSTREAM_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
DATASET_URL = (
    f"https://raw.githubusercontent.com/snap-research/locomo/{UPSTREAM_COMMIT}/data/locomo10.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read LoCoMo dataset {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("LoCoMo dataset root must be a JSON array")
    for index, sample in enumerate(data):
        if not isinstance(sample, dict) or not isinstance(sample.get("sample_id"), str):
            raise ValueError(f"LoCoMo sample {index} has no sample_id")
        if not isinstance(sample.get("conversation"), dict) or not isinstance(
            sample.get("qa"), list
        ):
            raise ValueError(f"LoCoMo sample {sample['sample_id']} has invalid annotations")
    return data


def download_dataset(path: Path, *, force: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or force:
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            urllib.request.urlretrieve(DATASET_URL, temporary)
            if sha256(temporary) != DATASET_SHA256:
                raise ValueError("downloaded LoCoMo dataset SHA-256 does not match pinned data")
            load_dataset(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    if sha256(path) != DATASET_SHA256:
        raise ValueError("local LoCoMo dataset SHA-256 does not match pinned data")
    load_dataset(path)
    return path


def sessions_from_conversation(conversation: dict) -> tuple[list[list[dict]], list[str]]:
    sessions: list[list[dict]] = []
    dates: list[str] = []
    session_numbers = sorted(
        int(key.removeprefix("session_"))
        for key, value in conversation.items()
        if key.startswith("session_")
        and key.removeprefix("session_").isdigit()
        and isinstance(value, list)
    )
    for number in session_numbers:
        sessions.append(conversation[f"session_{number}"])
        date = conversation.get(f"session_{number}_date_time", "")
        dates.append(str(date))
    return sessions, dates


def iter_questions(dataset: list[dict], *, categories: set[int]) -> Iterator[dict]:
    for sample in dataset:
        sessions, dates = sessions_from_conversation(sample["conversation"])
        for index, qa in enumerate(sample["qa"], start=1):
            category = int(qa["category"])
            if category not in categories:
                continue
            yield {
                "question_id": f"{sample['sample_id']}-q{index:04d}",
                "sample_id": sample["sample_id"],
                "sessions": sessions,
                "dates": dates,
                "question": str(qa["question"]),
                "answer": str(qa.get("answer", "")),
                "category": category,
                "evidence": qa.get("evidence", []),
            }


def dataset_summary(dataset: list[dict]) -> dict[str, object]:
    counts = Counter(str(int(qa["category"])) for sample in dataset for qa in sample["qa"])
    return {
        "conversation_count": len(dataset),
        "question_count": sum(counts.values()),
        "category_counts": dict(sorted(counts.items())),
    }
