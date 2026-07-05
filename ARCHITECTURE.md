# VLAN Manager — Architecture Overview

> **Production-grade network VLAN allocation and management system**
> FastAPI application with a MongoDB backend, clean layered architecture, and per-site (decentralized) VLAN allocation.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Layer Breakdown](#layer-breakdown)
3. [Data Model](#data-model)
4. [Data Flow](#data-flow)
5. [Design Patterns](#design-patterns)
6. [Performance & Concurrency](#performance--concurrency)
7. [Validation](#validation)

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         Web UI (static/)                       │
│              HTML + CSS + vanilla JS, dark/light theme         │
└───────────────────────────────┬──────────────────────────────┘
                                │ HTTP (JSON)
┌───────────────────────────────▼──────────────────────────────┐
│                        API Layer (src/api)                     │
│        FastAPI routes, auth dependency, request models         │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                     Service Layer (src/services)               │
│   allocation · segment · stats · export · logs (business rules)│
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│              DatabaseUtils facade (src/utils/database)         │
│      allocation · queries · CRUD · statistics (thin wrappers)  │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                    Mongo Layer (src/database)                  │
│   mongo_client · mongo_segments · mongo_storage · cache        │
└───────────────────────────────┬──────────────────────────────┘
                                │ Motor (async)
┌───────────────────────────────▼──────────────────────────────┐
│                            MongoDB                             │
│                   collection: segments                        │
└──────────────────────────────────────────────────────────────┘
```

**Principles**: strict separation of concerns, async I/O throughout, fail-fast configuration, and a per-site model with no VRF or external IPAM.

---

## Layer Breakdown

### API Layer — `src/api/routes.py`
Thin FastAPI handlers. Each route validates auth (HTTP Basic or session cookie via `require_auth`), deserializes into a Pydantic model, and delegates to a service. Request models use `extra="forbid"`, so unknown fields (e.g. a legacy `vrf`) are rejected with HTTP 422.

### Service Layer — `src/services/`
Business logic and orchestration:
- **allocation_service** — allocate/release a VLAN for a cluster (idempotent: re-allocating a cluster returns its existing VLAN).
- **segment_service** — segment CRUD, bulk CSV import, per-site VLAN-existence checks.
- **stats_service** — per-site statistics; health check pings MongoDB (`get_db().command("ping")`).
- **export_service** — CSV/Excel via pandas/openpyxl.
- **logs_service** — access to the app log file.

Service methods are wrapped with `@handle_db_errors`, `@retry_on_network_error`, and `@log_operation_timing` (bundled as `@db_operation`).

### DatabaseUtils Facade — `src/utils/database/`
A stable, aggregated interface (`DatabaseUtils`) over focused modules — `allocation_utils`, `segment_queries`, `segment_crud`, `statistics_utils` — so services don't import the Mongo layer directly.

### Mongo Layer — `src/database/`
- **mongo_client.py** — creates the `AsyncIOMotorClient`, exposes `get_db()` / `get_segments_collection()`.
- **mongo_storage.py** — `init_storage()` connects and ensures indexes; `close_storage()` shuts down.
- **mongo_segments.py** — `get_segments`, `get_segment_by_id`, `create_segment`, `update_segment`, `delete_segment`, `allocate_segment`.
- **mongo_utils.py** — `_doc_to_segment` (ObjectId→str), `_to_object_id` (str→ObjectId with HTTP 400).
- **cache.py** — short-TTL in-memory cache with in-flight request coalescing.

---

## Data Model

Collection **`segments`**:

| Field | Type | Notes |
|-------|------|-------|
| `_id` | ObjectId | returned to callers as `str` |
| `site` | str | e.g. `site1` |
| `vlan_id` | int | 1–4094 |
| `epg_name` | str | endpoint group name |
| `segment` | str | CIDR, e.g. `192.168.1.0/24` |
| `dhcp` | bool | |
| `description` | str | |
| `cluster_name` | str \| None | `None` = available; comma-separated = shared |
| `allocated_at` | datetime \| None | |
| `released` | bool | |
| `released_at` | datetime \| None | |

**Indexes** (`init_storage()`):
- `unique({site, vlan_id})` — one VLAN ID per site
- `unique({segment})` — globally unique CIDR
- `{cluster_name}` — allocation lookups
- `{site}` — site filtering

---

## Data Flow

### Create Segment
```
POST /api/segments → SegmentService.create_segment()
  → validate (site, VLAN, EPG, CIDR, site-prefix, overlap, per-site uniqueness)
  → check_vlan_exists(site, vlan_id)
  → DatabaseUtils.create_segment() → Mongo insert (+ cache invalidate)
```

### Allocate VLAN (atomic)
```
POST /api/allocate-vlan {cluster_name, site} → AllocationService.allocate_vlan()
  → find_existing_allocation()  (idempotent short-circuit)
  → find_and_allocate_segment() → allocate_segment():
        find_one_and_update(
          {site, cluster_name: None},
          {$set: {cluster_name, allocated_at, released:false}},
          sort=[(vlan_id, 1)], return_document=AFTER)
```
`find_one_and_update` makes allocation a single atomic operation — concurrent requests can never be handed the same segment.

### Release VLAN
```
POST /api/release-vlan {cluster_name, site} → AllocationService.release_vlan()
  → release_segment(): full release, or for shared segments removes just that cluster
```

---

## Design Patterns

- **Facade** — `DatabaseUtils` and `Validators` present one aggregated surface over focused modules.
- **Service layer** — business logic isolated from HTTP concerns.
- **DTOs** — Pydantic models for type-safe, validated request/response bodies.
- **Fail-fast configuration** — startup aborts on missing `MONGODB_URL` or incomplete `SITE_PREFIXES`.
- **Decorator stack** — cross-cutting error handling, retries, and timing applied uniformly to service methods.

---

## Performance & Concurrency

- **Async everywhere** — Motor is fully async; the event loop is never blocked on DB I/O.
- **Atomic allocation** — `find_one_and_update` avoids the read-then-write race entirely (no locks needed).
- **Short-TTL cache** — the full segments list is cached (~60s) in memory with in-flight coalescing, so a burst of concurrent list/stat requests triggers a single DB read; every write invalidates the cache.
- **Indexes** — the compound and single-field indexes back the hot query paths (per-site listing, allocation lookup, uniqueness enforcement).

---

## Validation

Layered validators in `src/utils/validators/`:

- **Input** — site membership, VLAN ID range (1–4094), EPG name (length + safe charset), cluster name, description.
- **Network** — CIDR format & strict network address, **site IP-prefix enforcement**, subnet mask /16–/31, reserved-range rejection, overlap detection.
- **Organization** — allocation state (cannot delete an allocated segment), **per-site EPG-name uniqueness**.

Per-site VLAN uniqueness is enforced twice: at the application layer (`check_vlan_exists`) and by the MongoDB `unique({site, vlan_id})` index — so even a race that slips past the app is rejected by the database.
