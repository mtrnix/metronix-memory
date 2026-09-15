"""Shared run-identity manifest for the agent-memory benchmarks.

Both LongMemEval and LoCoMo write a ``<results>.manifest.json`` and a
``<results>.query_set.json`` next to their answers file so any two runs can be
checked for comparability after the fact:

- ``manifest.json`` — dataset bytes (sha256), the exact ordered question set
  (``question_ids_sha256``), repository revision + dirty flag, and the full
  retrieval configuration the run used.
- ``query_set.json`` — the ordered list of ``question_id`` values actually
  executed, so a later run can replay exactly the same set.

Secrets never enter a manifest: callers pass an already-sanitized ``config`` /
``stack`` mapping (endpoint identity, model names — no keys).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

MANIFEST_SCHEMA_VERSION = 2
QUERY_SET_SCHEMA_VERSION = 1

_MANIFEST_SUFFIX = ".manifest.json"
_QUERY_SET_SUFFIX = ".query_set.json"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def sha256_file(path: Path | str) -> str:
    """Streaming SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def question_ids_digest(question_ids: Sequence[str]) -> str:
    """Order-sensitive digest of the exact question-id list a run executed.

    Newline-joined so a reordering, an addition, or a removal all change the
    hash. This is the machine-checkable form of "same set of queries".
    """
    return sha256_text("\n".join(question_ids))


def sanitized_endpoint_identity(url: str) -> str:
    """Normalized ``scheme://host[:port]/path`` — no credentials, no query.

    Lets a manifest record *which* Metronix a run hit without leaking a token
    that may be embedded in the URL.
    """
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    if not scheme or host is None:
        raise ValueError(f"not an absolute URL: {url!r}")
    host = host.lower()
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    port = parsed.port
    is_default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or is_default else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path.rstrip("/"), "", ""))


# ---------------------------------------------------------------------------
# Repository identity
# ---------------------------------------------------------------------------


def git_revision(repo_root: Path | str) -> dict[str, Any]:
    """Return ``{"revision": <sha|"unknown">, "dirty": <bool|None>}``.

    ``dirty`` is ``None`` when the working tree state could not be read (no git,
    not a repo) — distinct from a known-clean ``False``.
    """

    def _run(args: list[str]) -> str | None:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(repo_root),
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    revision = _run(["rev-parse", "HEAD"])
    porcelain = _run(["status", "--porcelain"])
    return {
        "revision": revision or "unknown",
        "dirty": bool(porcelain) if porcelain is not None else None,
    }


# ---------------------------------------------------------------------------
# Query set
# ---------------------------------------------------------------------------


def build_query_set(
    *,
    benchmark: str,
    selector: Mapping[str, Any],
    question_ids: Sequence[str],
) -> dict[str, Any]:
    """The ordered question set a run will execute, plus its digest."""
    ids = list(question_ids)
    return {
        "schema_version": QUERY_SET_SCHEMA_VERSION,
        "benchmark": benchmark,
        "order": "dataset",
        "selector": dict(selector),
        "question_count": len(ids),
        "question_ids_sha256": question_ids_digest(ids),
        "question_ids": ids,
    }


def query_set_summary(query_set: Mapping[str, Any]) -> dict[str, Any]:
    """The query set without the full id list — small enough to embed in a manifest."""
    return {
        "order": query_set["order"],
        "selector": dict(query_set["selector"]),
        "question_count": query_set["question_count"],
        "question_ids_sha256": query_set["question_ids_sha256"],
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    benchmark: str,
    repo_root: Path | str,
    dataset: Mapping[str, Any],
    query_set: Mapping[str, Any],
    config: Mapping[str, Any],
    stack: Mapping[str, Any],
    metrics_requested: Sequence[str],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the run-identity manifest.

    ``query_set`` is the full object from :func:`build_query_set`; only its
    summary is embedded here (the full id list lives in ``query_set.json``).
    """
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "benchmark": benchmark,
        "run_id": run_id or uuid4().hex,
        "started_at": datetime.now(UTC).isoformat(),
        "repository": git_revision(repo_root),
        "dataset": dict(dataset),
        "query_set": query_set_summary(query_set),
        "config": dict(config),
        "stack": dict(stack),
        "metrics_requested": list(metrics_requested),
    }


# ---------------------------------------------------------------------------
# Artifact paths + IO
# ---------------------------------------------------------------------------


def manifest_path(results_path: Path | str) -> Path:
    p = Path(results_path)
    return p.with_suffix(p.suffix + _MANIFEST_SUFFIX)


def resolve_run_identity(
    results_path: Path | str,
    *,
    benchmark: str,
    retrieval_mode: str = "unspecified",
    prefix_override: str | None = None,
    fresh: bool = False,
) -> tuple[str, str]:
    """Return ``(run_id, agent_id_prefix)`` for this run.

    A fresh run gets a new ``run_id`` and an agent-id prefix that embeds it, so a
    later run cannot search over this run's stored memories. A **resume** (the
    manifest already exists and ``fresh`` is False) reads both back, so every
    question in one results file uses one memory namespace.
    """
    existing = manifest_path(results_path)
    if not fresh and existing.is_file():
        try:
            data = json.loads(existing.read_text(encoding="utf-8"))
            prior_id = data["run_id"]
            prior_prefix = data["config"]["agent_id_prefix"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        else:
            if isinstance(prior_id, str) and isinstance(prior_prefix, str):
                return prior_id, prior_prefix

    run_id = uuid4().hex
    if prefix_override:
        return run_id, prefix_override
    parts = [benchmark]
    if retrieval_mode and retrieval_mode != "unspecified":
        parts.append(retrieval_mode)
    parts.append(run_id[:8])
    return run_id, "-".join(parts)


def query_set_path(results_path: Path | str) -> Path:
    p = Path(results_path)
    return p.with_suffix(p.suffix + _QUERY_SET_SUFFIX)


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_manifest(results_path: Path | str, manifest: Mapping[str, Any]) -> Path:
    return _write_json(manifest_path(results_path), manifest)


def write_query_set(results_path: Path | str, query_set: Mapping[str, Any]) -> Path:
    return _write_json(query_set_path(results_path), query_set)


def load_query_set(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("question_ids"), list):
        raise ValueError(f"not a benchmark query_set file: {path}")
    return data


def write_run_artifacts(
    results_path: Path | str,
    *,
    manifest: Mapping[str, Any],
    query_set: Mapping[str, Any],
) -> tuple[Path, Path]:
    """Write both sidecars; return ``(manifest_path, query_set_path)``."""
    return (
        write_manifest(results_path, manifest),
        write_query_set(results_path, query_set),
    )
