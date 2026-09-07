#!/usr/bin/env python3
"""One-shot migration: retire shared segments (comma-separated cluster_name).

One segment now belongs to at most ONE cluster. Any segment whose
`cluster_name` still holds a comma-separated list predates that rule, and this
script refuses to guess which cluster keeps it — an operator must decide:

    python scripts/migrate_drop_shared_clusters.py --report
        List every shared segment (CIDR, site, vlan, the cluster list).
        This is also the default when no mode is given. Never modifies data.

    python scripts/migrate_drop_shared_clusters.py \
        --segment 192.168.1.0/24 --split-to cluster-prod-01
        Resolve ONE segment explicitly: keep `cluster-prod-01` (which must be
        one of the names already on the segment) and drop the rest. Repeat per
        shared segment until --report comes back empty.

Run this BEFORE deploying the code that drops shared-segment support: the
allocate-segment workflow verifies its allocation by comparing `cluster_name`
with equality, so a leftover comma list would fail its read-back check.

Connection uses the same env vars as the app (MONGODB_URL required,
MONGODB_DB_NAME default 'segments-manager', MONGODB_TLS_INSECURE honoured), or
override via --uri/--db. Requires pymongo (a motor dependency, already installed).
"""

from __future__ import annotations

import argparse
import os
import sys

from pymongo import MongoClient


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _shared_filter() -> dict:
    return {"cluster_name": {"$regex": ","}}


def _report(coll) -> int:
    shared = list(coll.find(_shared_filter()))
    if not shared:
        print("No shared segments found — nothing to migrate.")
        return 0
    print(f"{len(shared)} shared segment(s) need an explicit --split-to decision:\n")
    for seg in shared:
        print(f"  segment={seg.get('segment')!r} site={seg.get('site')!r} "
              f"vlan_id={seg.get('vlan_id')} type={seg.get('type')!r} "
              f"clusters={seg.get('cluster_name')!r}")
    print("\nResolve each with:\n"
          "  python scripts/migrate_drop_shared_clusters.py "
          "--segment <cidr> --split-to <cluster-to-keep>")
    return 1


def _split_to(coll, segment: str, keep: str) -> int:
    doc = coll.find_one({"segment": segment})
    if doc is None:
        print(f"ERROR: no segment {segment!r} found.")
        return 1
    current = doc.get("cluster_name") or ""
    clusters = [c.strip() for c in current.split(",") if c.strip()]
    if len(clusters) < 2:
        print(f"Segment {segment!r} is not shared (cluster_name={current!r}) — nothing to do.")
        return 0
    if keep not in clusters:
        print(f"ERROR: {keep!r} is not one of {segment!r}'s clusters {clusters} — "
              "refusing to assign a segment to a cluster that never held it.")
        return 1
    coll.update_one({"_id": doc["_id"]}, {"$set": {"cluster_name": keep}})
    dropped = [c for c in clusters if c != keep]
    print(f"Segment {segment!r}: kept {keep!r}, dropped {dropped}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.getenv("MONGODB_URL"),
                        help="Mongo connection string (default: $MONGODB_URL)")
    parser.add_argument("--db", default=os.getenv("MONGODB_DB_NAME", "segments-manager"),
                        help="database name (default: $MONGODB_DB_NAME or 'segments-manager')")
    parser.add_argument("--collection", default="segments")
    parser.add_argument("--report", action="store_true",
                        help="list shared segments without modifying anything (the default mode)")
    parser.add_argument("--segment", help="CIDR of the ONE shared segment to resolve")
    parser.add_argument("--split-to", metavar="CLUSTER",
                        help="the single cluster that keeps --segment; the rest are dropped")
    args = parser.parse_args()

    if bool(args.segment) != bool(args.split_to):
        parser.error("--segment and --split-to must be given together")
    if args.report and args.segment:
        parser.error("--report and --segment/--split-to are mutually exclusive")
    if not args.uri:
        parser.error("no Mongo URI: set MONGODB_URL or pass --uri")

    client_kwargs: dict = {}
    if _truthy(os.getenv("MONGODB_TLS_INSECURE")):
        client_kwargs.update(tls=True, tlsAllowInvalidCertificates=True)

    client = MongoClient(args.uri, **client_kwargs)
    coll = client[args.db][args.collection]
    print(f"Target: db={args.db!r} collection={args.collection!r}")

    try:
        if args.segment:
            return _split_to(coll, args.segment, args.split_to)
        return _report(coll)
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
