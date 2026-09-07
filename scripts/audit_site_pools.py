#!/usr/bin/env python3
"""Read-only audit: which stored segments fall outside their site's pool?

Run this BEFORE committing to a set of SITE_NETWORKS pool CIDRs. The pool rule
(NetworkValidators.validate_segment_format) is enforced only on create, and
`segment` is immutable with no re-validating update path — so pre-existing
out-of-pool segments keep serving traffic indefinitely. What they lose is
reproducibility: a CSV re-import, a DR restore-and-recreate, or any "recreate
this segment" runbook will be rejected by the very rules that let the segment
exist. Use the output to choose pools that fit reality, or to decide
deliberately which segments to migrate.

Pay attention to `status` in the report: an out-of-pool segment that is
Allocated belongs to a live cluster, not just a stale row.

The script never writes — there is no --dry-run because there is nothing to dry
run. It reuses src.config.settings.parse_site_networks so it can never disagree
with the server about what a valid topology is.

    SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16"}}' \
        python scripts/audit_site_pools.py --uri mongodb://localhost:27017

Exit codes: 0 clean · 1 violations found (with --fail-on-violation) · 2 bad config.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def classify(doc: dict, pools: dict, canonical: dict) -> str | None:
    """Return a violation category for this document, or None if it is fine."""
    site = (doc.get("site") or "").strip()
    resolved = canonical.get(site.lower())
    if resolved is None:
        return "unconfigured_site"

    segment = doc.get("segment")
    try:
        network = ipaddress.ip_network(segment, strict=False)
    except (ValueError, TypeError):
        return "unparseable"

    pool = pools[resolved]
    # Version check first: subnet_of across families raises TypeError.
    if network.version != pool.version or not network.subnet_of(pool):
        return "outside_pool"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.getenv("MONGODB_URL"),
                        help="Mongo connection string (default: $MONGODB_URL)")
    parser.add_argument("--db", default=os.getenv("MONGODB_DB_NAME", "segments-manager"),
                        help="database name (default: $MONGODB_DB_NAME or 'segments-manager')")
    parser.add_argument("--collection", default="segments")
    parser.add_argument("--site-networks", default=os.getenv("SITE_NETWORKS"),
                        help="topology JSON to audit against (default: $SITE_NETWORKS). "
                             "Pass a candidate value here to try pools before adopting them.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--fail-on-violation", action="store_true",
                        help="exit 1 when any segment is out of pool")
    args = parser.parse_args()

    if not args.uri:
        parser.error("no Mongo URI: set MONGODB_URL or pass --uri")
    if not args.site_networks:
        parser.error("no topology: set SITE_NETWORKS or pass --site-networks")

    # settings.py fail-fasts on a missing MONGODB_URL at import time, and we may
    # have been given the URI via --uri only.
    os.environ.setdefault("MONGODB_URL", args.uri)
    from src.config.settings import parse_site_networks

    networks, pools, errors = parse_site_networks(args.site_networks)
    if errors:
        print("SITE_NETWORKS is invalid:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 2

    canonical = {site.lower(): site for site in networks}

    client_kwargs: dict = {}
    if _truthy(os.getenv("MONGODB_TLS_INSECURE")):
        client_kwargs.update(tls=True, tlsAllowInvalidCertificates=True)

    client = MongoClient(args.uri, **client_kwargs)
    coll = client[args.db][args.collection]

    per_site: dict = {site: {"total": 0, "ok": 0} for site in networks}
    violations: list = []
    total = 0

    for doc in coll.find({}, {"segment": 1, "site": 1, "type": 1, "vlan_id": 1,
                              "status": 1, "cluster_name": 1}):
        total += 1
        site = (doc.get("site") or "").strip()
        resolved = canonical.get(site.lower())
        if resolved:
            per_site[resolved]["total"] += 1

        category = classify(doc, pools, canonical)
        if category is None:
            per_site[resolved]["ok"] += 1
            continue

        violations.append({
            "category": category,
            "segment": doc.get("segment"),
            "site": doc.get("site"),
            "type": doc.get("type"),
            "vlan_id": doc.get("vlan_id"),
            "status": doc.get("status"),
            "cluster_name": doc.get("cluster_name"),
            "pool": str(pools[resolved]) if resolved else None,
        })

    client.close()

    if args.json:
        print(json.dumps({"total": total, "per_site": per_site,
                          "violations": violations}, indent=2, default=str))
    else:
        print(f"Audited {total} segment(s) in db={args.db!r} "
              f"collection={args.collection!r}\n")
        for site, pool in pools.items():
            counts = per_site[site]
            print(f"  {site:12s} pool={str(pool):20s} "
                  f"total={counts['total']:<5d} ok={counts['ok']:<5d} "
                  f"violations={counts['total'] - counts['ok']}")

        if violations:
            print(f"\n{'CATEGORY':<20} {'SEGMENT':<20} {'SITE':<10} {'TYPE':<10} "
                  f"{'VLAN':<6} {'STATUS':<10} CLUSTER")
            for v in violations:
                print(f"{v['category']:<20} {str(v['segment']):<20} "
                      f"{str(v['site']):<10} {str(v['type']):<10} "
                      f"{str(v['vlan_id']):<6} {str(v['status']):<10} "
                      f"{v['cluster_name'] or '-'}")

        allocated = [v for v in violations if v["status"] == "Allocated"]
        print(f"\nGATE: {len(violations)} violating segment(s)"
              + (f", {len(allocated)} of them ALLOCATED to a live cluster"
                 if allocated else ""))

    return 1 if violations and args.fail_on_violation else 0


if __name__ == "__main__":
    sys.exit(main())
