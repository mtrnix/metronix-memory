"""Issue #488 methodology check: reproduce the #461 accumulation pattern on
the dev stand, then re-run ``baseline_duplication_rate.py`` to confirm the
baseline script actually detects non-zero duplication (not just a correct
zero on an empty corpus).

This does NOT revert the #461/#473 fix (delete-before-add is still active on
the connector sync path on current ``main``). Reverting the fix and running a
real connector against a mock source is out of scope for a dev-stand sanity
check. Instead it reproduces the fix's *effect* directly at the storage layer
it patched: the pre-fix bug was "write a new chunk without deleting the old
one" (``storage/qdrant.py`` mints a fresh random ``uuid4()`` point id on every
call, and the connector path used to call it without ``incremental=True``).
This script does exactly that -- copies an existing point's vectors + payload
byte-for-byte into new points under new ids -- which is indistinguishable,
from the search-result side, from what the unpatched connector path
produced. It mirrors #461's own observed progression (3 -> 6 -> 9 chunks for
one doc_label across repeated re-ingests): each selected doc_label gets 2
extra copies, i.e. count 1 -> 3, matching the issue's "second sync" +
"cursor-reset re-sync" doubling/tripling.

Targets QA-AURORA-RUNBOOK and QA-AURORA-UPDATE -- both are hit by several
"entity" queries in the #497 audit's query set (see
``scripts/audits/issue-497/audit_channel_scores.py``), so the follow-up
baseline run should surface them.

Records every added point id in ``repro_added_ids.json`` so
``cleanup_461_duplication.py`` can remove exactly what this script added and
nothing else.

Run inside the metronix-core container:

    docker cp scripts/audits/issue-488/reproduce_461_duplication.py \
        metronix-full-api:/tmp/
    docker exec metronix-full-api python /tmp/reproduce_461_duplication.py
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx

QDRANT_URL = "http://qdrant:6333"
COLLECTION = "mem_docs_hybrid"  # MTRNIX is the default workspace -> base collection name
TARGET_DOC_LABELS = ["QA-AURORA-RUNBOOK", "QA-AURORA-UPDATE"]
COPIES_PER_DOC = 2  # 1 original + 2 copies = 3, matching #461's "3 -> 6 -> 9" observation


def main() -> None:
    client = httpx.Client(timeout=30.0)

    scroll = client.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
        json={"limit": 100, "with_payload": True, "with_vector": True},
    )
    scroll.raise_for_status()
    points = scroll.json()["result"]["points"]

    originals = [p for p in points if p["payload"].get("doc_label") in TARGET_DOC_LABELS]
    found_labels = {p["payload"].get("doc_label") for p in originals}
    missing = set(TARGET_DOC_LABELS) - found_labels
    if missing:
        raise SystemExit(f"Target doc_label(s) not found in {COLLECTION}: {sorted(missing)}")

    before = client.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/count", json={"exact": True}
    ).json()["result"]["count"]

    new_points = []
    added_ids: list[dict] = []
    for orig in originals:
        for _ in range(COPIES_PER_DOC):
            new_id = str(uuid.uuid4())
            new_points.append(
                {
                    "id": new_id,
                    "vector": orig["vector"],
                    "payload": orig["payload"],
                }
            )
            added_ids.append(
                {
                    "new_id": new_id,
                    "copied_from": orig["id"],
                    "doc_label": orig["payload"].get("doc_label"),
                }
            )

    upsert = client.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={"points": new_points},
        params={"wait": "true"},
    )
    upsert.raise_for_status()

    after = client.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/count", json={"exact": True}
    ).json()["result"]["count"]

    out_path = Path(__file__).resolve().parent / "repro_added_ids.json"
    out_path.write_text(
        json.dumps(
            {
                "collection": COLLECTION,
                "target_doc_labels": TARGET_DOC_LABELS,
                "copies_per_doc": COPIES_PER_DOC,
                "count_before": before,
                "count_after": after,
                "added_ids": added_ids,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"collection: {COLLECTION}")
    print(f"target doc_labels: {TARGET_DOC_LABELS}")
    print(f"originals found: {len(originals)}  copies added: {len(new_points)}")
    print(f"point count: {before} -> {after}")
    print(f"Wrote {out_path} — run cleanup_461_duplication.py to undo this.")


if __name__ == "__main__":
    main()
