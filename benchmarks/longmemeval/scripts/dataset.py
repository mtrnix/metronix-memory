"""Pinned LongMemEval-cleaned dataset download, validation, and identity.

Mirrors ``benchmarks/locomo/scripts/dataset.py``: the files are pinned to a
specific Hugging Face revision and verified against a recorded SHA-256 on every
download and every run, so two runs cannot silently use different data.

Source: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BENCH_ROOT / "data"

# xiaowu0162/longmemeval-cleaned @ main — "Upload folder using huggingface_hub",
# 2025-09-19. Re-pin (and re-record the hashes below) deliberately, never by
# tracking ``main``.
HF_REVISION = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
_HF_RESOLVE = (
    f"https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/{HF_REVISION}"
)

VARIANTS: dict[str, dict[str, str]] = {
    "oracle": {
        "filename": "longmemeval_oracle.json",
        "url": f"{_HF_RESOLVE}/longmemeval_oracle.json",
        "sha256": "821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c",
    },
    "s": {
        "filename": "longmemeval_s_cleaned.json",
        "url": f"{_HF_RESOLVE}/longmemeval_s_cleaned.json",
        "sha256": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
    },
}

VARIANT_NAMES = tuple(VARIANTS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataset_path(variant: str) -> Path:
    _require_variant(variant)
    return DATA_DIR / VARIANTS[variant]["filename"]


def _require_variant(variant: str) -> None:
    if variant not in VARIANTS:
        raise ValueError(f"unknown LongMemEval variant {variant!r} (choose from {VARIANT_NAMES})")


def validate_dataset(data: object) -> list[dict]:
    """Structural check: a JSON array of question objects with ``question_id``."""
    if not isinstance(data, list):
        raise ValueError("LongMemEval dataset root must be a JSON array")
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or not isinstance(entry.get("question_id"), str):
            raise ValueError(f"LongMemEval entry {index} has no question_id")
    return data


def download_dataset(variant: str, *, force: bool = False) -> Path:
    """Download (if missing / forced) and verify the pinned dataset file."""
    _require_variant(variant)
    spec = VARIANTS[variant]
    path = dataset_path(variant)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists() or force:
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            urllib.request.urlretrieve(spec["url"], temporary)
            if sha256(temporary) != spec["sha256"]:
                raise ValueError(
                    f"downloaded LongMemEval {variant} dataset SHA-256 does not match the "
                    f"pinned value (expected {spec['sha256']})"
                )
            with temporary.open(encoding="utf-8") as handle:
                validate_dataset(json.load(handle))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    verify_dataset(variant)
    return path


def verify_dataset(variant: str) -> Path:
    """Raise unless the local file exists and matches the pinned SHA-256."""
    _require_variant(variant)
    path = dataset_path(variant)
    if not path.exists():
        raise FileNotFoundError(
            f"LongMemEval {variant} dataset not found: {path}\n"
            f"Run: python scripts/run_benchmark.py download --variant {variant}"
        )
    if sha256(path) != VARIANTS[variant]["sha256"]:
        raise ValueError(
            f"local LongMemEval {variant} dataset SHA-256 does not match the pinned value "
            f"({path}); re-download with --force"
        )
    return path


def load_dataset(variant: str) -> list[dict]:
    """Verify identity, then load and structurally validate the dataset."""
    path = verify_dataset(variant)
    with path.open(encoding="utf-8") as handle:
        return validate_dataset(json.load(handle))


def select_questions(dataset: list[dict], *, max_questions: int | None = None) -> list[dict]:
    """Deterministic question selection: dataset order, first ``max_questions``."""
    return dataset if max_questions is None else dataset[:max_questions]


def question_ids(dataset: list[dict], *, max_questions: int | None = None) -> list[str]:
    return [
        entry["question_id"] for entry in select_questions(dataset, max_questions=max_questions)
    ]


def dataset_identity(variant: str, *, question_count: int) -> dict[str, object]:
    """The ``dataset`` block for a run manifest."""
    spec = VARIANTS[variant]
    return {
        "name": "longmemeval-cleaned",
        "variant": variant,
        "source_url": spec["url"],
        "upstream_ref": HF_REVISION,
        "sha256": spec["sha256"],
        "question_count": question_count,
    }
