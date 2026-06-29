"""Export LLM generation log rows to a fine-tuning dataset file.

Usage examples:
    python scripts/export_llm_dataset.py --call-site rag_answer --out dataset.jsonl
    python scripts/export_llm_dataset.py \\
        --call-site rag_answer --call-site query_classifier \\
        --workspace-id MTRNIX \\
        --from 2026-01-01 --to 2026-12-31 \\
        --format openai-chat-ft \\
        --out out.jsonl
    python scripts/export_llm_dataset.py --include-eval --out full.jsonl
    python scripts/export_llm_dataset.py --include-failed --out all.jsonl
    python scripts/export_llm_dataset.py --no-include-zero-tokens --out quality.jsonl

Formats:
    openai-chat-ft (default)
        {"messages": [...request_messages..., {"role": "assistant", "content": "<answer>"}]}
        Matches the OpenAI fine-tuning Chat Completions format.

    openai-completion-legacy
        {"prompt": "<concatenated messages>", "completion": "<answer>"}
        Legacy text-completion-style fine-tunes (OpenAI, Mistral legacy API).

    messages-only
        Same wire shape as openai-chat-ft but labelled separately for
        HuggingFace / generic pipelines.

Filters applied by default:
    - success=true
    - response_content IS NOT NULL
    - source NOT IN ('benchmark', 'eval')  (pass --include-eval to disable)

Streams results from PostgreSQL in pages of 1000 rows; never loads the full
table into memory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime

# Ensure src/ is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from metronix.core.config import get_settings

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_EXCLUDED_SOURCES = ("benchmark", "eval")

_PAGE_SIZE = 1000


def _build_query(
    *,
    call_sites: list[str],
    workspace_ids: list[str],
    from_date: date | None,
    to_date: date | None,
    success_only: bool,
    include_eval: bool,
    include_zero_tokens: bool,
    limit: int | None,
) -> tuple[str, dict]:
    """Build a raw SQL SELECT with bind params.

    Returns (sql_template, params_dict). Uses cursor-based pagination via
    ``min_id`` param injected at call time; the function only builds the
    WHERE body and ORDER/LIMIT suffix.
    """
    where_clauses: list[str] = ["id > :min_id"]
    params: dict = {}

    if success_only:
        where_clauses.append("success = TRUE")
        where_clauses.append("response_content IS NOT NULL")

    if not include_eval:
        where_clauses.append("(source IS NULL OR source NOT IN :excluded_sources)")
        params["excluded_sources"] = _EXCLUDED_SOURCES

    if not include_zero_tokens:
        where_clauses.append(
            "(metadata IS NULL OR (metadata->>'zero_tokens')::boolean IS NOT TRUE)"
        )

    if call_sites:
        where_clauses.append("call_site = ANY(:call_sites)")
        params["call_sites"] = call_sites

    if workspace_ids:
        where_clauses.append("workspace_id = ANY(:workspace_ids)")
        params["workspace_ids"] = workspace_ids

    if from_date is not None:
        where_clauses.append("created_at >= :from_date")
        params["from_date"] = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=UTC)

    if to_date is not None:
        where_clauses.append("created_at < :to_date")
        params["to_date"] = datetime.combine(to_date, datetime.min.time()).replace(tzinfo=UTC)

    where_sql = " AND ".join(where_clauses)

    page_limit = _PAGE_SIZE if limit is None else min(_PAGE_SIZE, limit)

    sql = f"""
        SELECT
            id,
            call_site,
            source,
            workspace_id,
            provider,
            model,
            request_messages,
            response_content,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            latency_ms,
            success,
            error_class,
            metadata
        FROM llm_generation_log
        WHERE {where_sql}
        ORDER BY id ASC
        LIMIT :page_limit
    """
    params["page_limit"] = page_limit
    return sql, params


# ---------------------------------------------------------------------------
# Format converters
# ---------------------------------------------------------------------------


def _messages_to_prompt(messages: list[dict]) -> str:
    """Concatenate message list into a plain text prompt (legacy format)."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # Handle content that may be a list of parts (e.g. multimodal shape)
            content = " ".join(
                p.get("text", "") if isinstance(p, dict) else str(p) for p in content
            )
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _row_to_jsonl(row: dict, fmt: str) -> str:
    """Convert a DB row dict to a JSONL line string."""
    messages = row["request_messages"]
    if isinstance(messages, str):
        messages = json.loads(messages)
    response = row["response_content"] or ""

    if fmt in ("openai-chat-ft", "messages-only"):
        record = {
            "messages": [
                *messages,
                {"role": "assistant", "content": response},
            ]
        }
    elif fmt == "openai-completion-legacy":
        record = {
            "prompt": _messages_to_prompt(messages),
            "completion": response,
        }
    else:
        raise ValueError(f"Unknown format: {fmt!r}")

    return json.dumps(record, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main export loop
# ---------------------------------------------------------------------------


def export(
    *,
    call_sites: list[str],
    workspace_ids: list[str],
    from_date: date | None,
    to_date: date | None,
    fmt: str,
    out_path: str,
    success_only: bool,
    include_eval: bool,
    include_zero_tokens: bool,
    limit: int | None,
) -> int:
    """Stream rows from PG and write JSONL. Returns count of rows written."""
    import sqlalchemy as sa

    settings = get_settings()
    engine = sa.create_engine(settings.postgres_sync_dsn)

    sql_template, base_params = _build_query(
        call_sites=call_sites,
        workspace_ids=workspace_ids,
        from_date=from_date,
        to_date=to_date,
        success_only=success_only,
        include_eval=include_eval,
        include_zero_tokens=include_zero_tokens,
        limit=limit,
    )

    written = 0
    min_id = 0

    with open(out_path, "w", encoding="utf-8") as fout, engine.connect() as conn:
        while True:
            params = {**base_params, "min_id": min_id}
            result = conn.execute(sa.text(sql_template), params)
            rows = result.mappings().all()
            if not rows:
                break

            for row in rows:
                line = _row_to_jsonl(dict(row), fmt)
                fout.write(line + "\n")
                written += 1
                if limit is not None and written >= limit:
                    break

            if limit is not None and written >= limit:
                break

            last_id = rows[-1]["id"]
            min_id = last_id

            if len(rows) < _PAGE_SIZE:
                # Last page
                break

    engine.dispose()
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export llm_generation_log rows to a fine-tuning dataset file.",
    )
    parser.add_argument(
        "--call-site",
        dest="call_sites",
        action="append",
        default=[],
        metavar="LABEL",
        help="Filter by call_site label (repeatable). Default: all.",
    )
    parser.add_argument(
        "--workspace-id",
        dest="workspace_ids",
        action="append",
        default=[],
        metavar="WS_ID",
        help="Filter by workspace_id (repeatable). Default: all.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Include rows with created_at >= this date (UTC).",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Include rows with created_at < this date (UTC).",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        default="openai-chat-ft",
        choices=["openai-chat-ft", "openai-completion-legacy", "messages-only"],
        help="Output format (default: openai-chat-ft).",
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="PATH",
        help="Output JSONL file path (required).",
    )
    parser.add_argument(
        "--success-only",
        dest="success_only",
        action="store_true",
        default=True,
        help="Include only rows where success=true (default: on).",
    )
    parser.add_argument(
        "--include-failed",
        dest="success_only",
        action="store_false",
        help="Include failed rows (overrides --success-only).",
    )
    parser.add_argument(
        "--include-eval",
        dest="include_eval",
        action="store_true",
        default=False,
        help="Include rows from benchmark/eval sources (default: excluded).",
    )
    parser.add_argument(
        "--include-zero-tokens",
        dest="include_zero_tokens",
        action="store_true",
        default=True,
        help="Include rows where all token counts are 0 (default: on).",
    )
    parser.add_argument(
        "--no-include-zero-tokens",
        dest="include_zero_tokens",
        action="store_false",
        help="Drop rows where metadata.zero_tokens=true.",
    )
    parser.add_argument(
        "--limit",
        dest="limit",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of rows to export.",
    )

    args = parser.parse_args()

    print(
        f"Exporting: call_sites={args.call_sites or 'all'}, "
        f"workspaces={args.workspace_ids or 'all'}, "
        f"format={args.fmt}, "
        f"success_only={args.success_only}, "
        f"include_eval={args.include_eval}, "
        f"include_zero_tokens={args.include_zero_tokens}, "
        f"limit={args.limit or 'none'}"
    )
    print(f"Output → {args.out}")

    try:
        count = export(
            call_sites=args.call_sites,
            workspace_ids=args.workspace_ids,
            from_date=args.from_date,
            to_date=args.to_date,
            fmt=args.fmt,
            out_path=args.out,
            success_only=args.success_only,
            include_eval=args.include_eval,
            include_zero_tokens=args.include_zero_tokens,
            limit=args.limit,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Done. Rows written: {count}")


if __name__ == "__main__":
    main()
