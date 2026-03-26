"""Load and validate evaluation test set from YAML."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TESTSET_PATH = (
    Path(__file__).parent.parent / "fixtures" / "search_quality_testset.yaml"
)


@dataclass
class EvalQuery:
    """Single evaluation query with expected doc_labels."""

    id: str
    text: str
    expected_doc_labels: set[str]
    category: str = "mixed"
    notes: str | None = None
    stable: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> EvalQuery:
        missing = [f for f in ("id", "text", "expected_doc_labels") if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        return cls(
            id=data["id"],
            text=data["text"],
            expected_doc_labels=set(data["expected_doc_labels"]),
            category=data.get("category", "mixed"),
            notes=data.get("notes"),
            stable=data.get("stable", True),
        )


@dataclass
class EvalTestSet:
    """Collection of evaluation queries."""

    queries: list[EvalQuery]
    version: str = "1.0"
    description: str = ""


def load_eval_testset(yaml_content: str) -> EvalTestSet:
    """Parse YAML string into EvalTestSet."""
    data = yaml.safe_load(yaml_content)
    queries_raw = data.get("queries", [])
    if not queries_raw:
        raise ValueError("Test set must contain at least 1 query")
    queries = [EvalQuery.from_dict(q) for q in queries_raw]
    ids = [q.id for q in queries]
    dupes = [qid for qid in ids if ids.count(qid) > 1]
    if dupes:
        raise ValueError(f"Duplicate query IDs: {set(dupes)}")
    return EvalTestSet(
        queries=queries,
        version=data.get("version", "1.0"),
        description=data.get("description", ""),
    )


def load_eval_testset_from_path(path: Path) -> EvalTestSet:
    """Load EvalTestSet from a YAML file."""
    return load_eval_testset(path.read_text(encoding="utf-8"))
