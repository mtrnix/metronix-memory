from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH_SCRIPTS = Path(__file__).resolve().parents[4] / "benchmarks" / "longmemeval" / "scripts"
sys.path.insert(0, str(BENCH_SCRIPTS))

import dataset as lme_dataset  # noqa: E402


def test_pin_is_a_commit_not_a_branch() -> None:
    assert len(lme_dataset.HF_REVISION) == 40
    for spec in lme_dataset.VARIANTS.values():
        assert f"/resolve/{lme_dataset.HF_REVISION}/" in spec["url"]
        assert "/resolve/main/" not in spec["url"]
        assert len(spec["sha256"]) == 64


def test_validate_dataset_rejects_non_array() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        lme_dataset.validate_dataset({"question_id": "q1"})


def test_validate_dataset_rejects_entry_without_question_id() -> None:
    with pytest.raises(ValueError, match="no question_id"):
        lme_dataset.validate_dataset([{"question": "?"}])


def test_verify_dataset_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lme_dataset, "DATA_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="download --variant oracle"):
        lme_dataset.verify_dataset("oracle")


def test_verify_dataset_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lme_dataset, "DATA_DIR", tmp_path)
    (tmp_path / "longmemeval_oracle.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match the pinned"):
        lme_dataset.verify_dataset("oracle")


def test_unknown_variant_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown LongMemEval variant"):
        lme_dataset.dataset_path("tiny")


def test_select_questions_is_dataset_order_prefix() -> None:
    data = [{"question_id": f"q{n}"} for n in range(10)]
    assert lme_dataset.question_ids(data, max_questions=3) == ["q0", "q1", "q2"]
    assert lme_dataset.question_ids(data, max_questions=None) == [f"q{n}" for n in range(10)]


def test_dataset_identity_shape() -> None:
    identity = lme_dataset.dataset_identity("s", question_count=42)
    assert identity["upstream_ref"] == lme_dataset.HF_REVISION
    assert identity["sha256"] == lme_dataset.VARIANTS["s"]["sha256"]
    assert identity["variant"] == "s"
    assert identity["question_count"] == 42


@pytest.mark.parametrize("variant", ["oracle", "s"])
def test_pinned_dataset_matches_recorded_hash_when_present(variant: str) -> None:
    """Real-data check: when the operator has downloaded the file, its bytes
    match the SHA-256 recorded in ``dataset.py``. Skipped in a clean checkout."""
    path = lme_dataset.dataset_path(variant)
    if not path.exists():
        pytest.skip(f"{path.name} not downloaded")
    loaded = lme_dataset.load_dataset(variant)  # verifies sha + structure
    assert isinstance(loaded, list) and loaded
    ids = lme_dataset.question_ids(loaded)
    assert len(ids) == len(set(ids))  # question ids are unique
    assert all(isinstance(i, str) for i in ids)
