#!/usr/bin/env python3
"""One-shot migration: rename the segment-connectivity display fields on segment
documents from the old `connectivity_*` names to `segment_connectivity_*`.

Renamed (segments collection):
    connectivity_requests               -> segment_connectivity_requests
    connectivity_requests_submitted_at  -> segment_connectivity_requests_submitted_at
    connectivity_failure                -> segment_connectivity_failure
    connectivity_failure_at             -> segment_connectivity_failure_at

These hold transient UI state (pending firewall request ids + the terminal
failure note), so the migration is low-risk, but it is written to be safe
regardless of deploy order and to be idempotent (re-runnable):

  * where only the OLD field exists                -> $rename old -> new
  * where BOTH exist (new code already wrote the   -> $unset the stale OLD
    current value)                                    (never overwrite current data)

Recommended order for zero ambiguity: run this BEFORE deploying the renamed
code, so only the OLD fields exist. But either order is safe.

Connection uses the same env vars as the app (MONGODB_URL required,
MONGODB_DB_NAME default 'segments_manager', MONGODB_TLS_INSECURE honoured), or
override via --uri/--db. Requires pymongo (a motor dependency, already installed).

    python scripts/migrate_segment_connectivity_fields.py --dry-run
    python scripts/migrate_segment_connectivity_fields.py
"""

from __future__ import annotations

import argparse
import os
import sys

from pymongo import MongoClient

RENAMES = {
    "connectivity_requests": "segment_connectivity_requests",
    "connectivity_requests_submitted_at": "segment_connectivity_requests_submitted_at",
    "connectivity_failure": "segment_connectivity_failure",
    "connectivity_failure_at": "segment_connectivity_failure_at",
}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.getenv("MONGODB_URL"),
                        help="Mongo connection string (default: $MONGODB_URL)")
    parser.add_argument("--db", default=os.getenv("MONGODB_DB_NAME", "segments_manager"),
                        help="database name (default: $MONGODB_DB_NAME or 'segments_manager')")
    parser.add_argument("--collection", default="segments")
    parser.add_argument("--dry-run", action="store_true",
                        help="report affected counts without modifying anything")
    args = parser.parse_args()

    if not args.uri:
        parser.error("no Mongo URI: set MONGODB_URL or pass --uri")

    client_kwargs: dict = {}
    if _truthy(os.getenv("MONGODB_TLS_INSECURE")):
        client_kwargs.update(tls=True, tlsAllowInvalidCertificates=True)

    client = MongoClient(args.uri, **client_kwargs)
    coll = client[args.db][args.collection]
    print(f"Target: db={args.db!r} collection={args.collection!r}"
          f"{'  (DRY RUN)' if args.dry_run else ''}")

    total_renamed = total_dropped = 0
    for old, new in RENAMES.items():
        rename_filter = {old: {"$exists": True}, new: {"$exists": False}}
        drop_filter = {old: {"$exists": True}, new: {"$exists": True}}
        n_rename = coll.count_documents(rename_filter)
        n_drop = coll.count_documents(drop_filter)
        if not args.dry_run:
            if n_rename:
                coll.update_many(rename_filter, {"$rename": {old: new}})
            if n_drop:
                coll.update_many(drop_filter, {"$unset": {old: ""}})
        total_renamed += n_rename
        total_dropped += n_drop
        print(f"  {old:38s} -> {new:46s} rename={n_rename} drop_stale={n_drop}")

    verb = "would rename" if args.dry_run else "renamed"
    verb2 = "would drop" if args.dry_run else "dropped"
    print(f"\n{verb} {total_renamed} field value(s); {verb2} {total_dropped} stale duplicate(s).")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
