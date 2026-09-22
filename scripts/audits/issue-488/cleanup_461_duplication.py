"""Undo ``reproduce_461_duplication.py``: delete exactly the point ids it
recorded in ``repro_added_ids.json``, leaving the dev workspace's Qdrant
collection back at its original point count. Safe to run multiple times
(deleting an already-deleted id is a no-op in Qdrant).

Run inside the metronix-core container:

    docker cp scripts/audits/issue-488/cleanup_461_duplication.py \
        metronix-full-api:/tmp/
    docker exec metronix-full-api python /tmp/cleanup_461_duplication.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

QDRANT_URL = "http://qdrant:6333"


def main() -> None:
    record_path = Path(__file__).resolve().parent / "repro_added_ids.json"
    if not record_path.is_file():
        raise SystemExit(f"No {record_path} found — nothing to clean up.")

    record = json.loads(record_path.read_text(encoding="utf-8"))
    collection = record["collection"]
    ids = [entry["new_id"] for entry in record["added_ids"]]

    client = httpx.Client(timeout=30.0)
    before = client.post(
        f"{QDRANT_URL}/collections/{collection}/points/count", json={"exact": True}
    ).json()["result"]["count"]

    resp = client.post(
        f"{QDRANT_URL}/collections/{collection}/points/delete",
        json={"points": ids},
        params={"wait": "true"},
    )
    resp.raise_for_status()

    after = client.post(
        f"{QDRANT_URL}/collections/{collection}/points/count", json={"exact": True}
    ).json()["result"]["count"]

    print(f"collection: {collection}")
    print(f"deleted {len(ids)} point id(s) recorded in {record_path.name}")
    print(f"point count: {before} -> {after}  (expected original: {record['count_before']})")
    if after != record["count_before"]:
        print("WARNING: count did not return to the recorded original — inspect manually.")


if __name__ == "__main__":
    main()
