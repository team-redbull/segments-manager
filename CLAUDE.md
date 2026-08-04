# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Segments Manager** is a production-grade network VLAN allocation and management system. It provides an intelligent API layer and web UI for allocating VLAN segments to clusters across multiple sites, with comprehensive validation. Segments are stored in **MongoDB**.

**Type**: FastAPI Web Application + REST API
**Primary Language**: Python 3.11
**Architecture Pattern**: Clean Architecture with service-oriented design
**Storage Backend**: MongoDB (via Motor async driver)
**Deployment**: Containerized (Podman/Docker), Kubernetes/OpenShift ready (Helm chart)

> **Decentralized, per-site model.** There is **no VRF** and **no centralized IPAM**. VLAN IDs and EPG names are unique **per site**. The database enforces this with a unique compound index `{site, vlan_id}`.

> **The segment CIDR is the natural key.** The `segment` field is globally unique (unique index) and immutable, and it is how the API identifies individual segments — reads/deletes take `?segment=<cidr>` as a query parameter, writes carry `segment` in the request body. The Mongo `ObjectId` is internal only; there are no `/api/segments/{id}` routes.

> **Every route lives under the plural `/api/segments`.** That includes the two allocation actions, which replaced the old top-level `/api/allocate-segment` and `/api/release-segment`: `POST /api/segments/allocate` `{cluster_name, site, type}` and `POST /api/segments/release` `{segment}`. Allocate acts on the collection — it picks a member out of the available pool, so it names no CIDR. Release is keyed by the CIDR exactly like `/segments/unlock`, since the CIDR is globally unique; it accepts **no** site, cluster_name or type (`extra="forbid"` rejects them). Release only ever performs `Allocated → Available`: an already-`Available` segment is an idempotent 200, and a `Locked` one is a **409** — nothing was allocated, and release must not become a second path to `Available`. Do not add a singular `/api/segment` prefix.

> **These three are POST, and that is deliberate.** `allocate`, `release` and `unlock` are RPC-style actions whose body only *names the target* (`{segment}`) — the change itself is encoded in the URL verb, not the payload. PUT/PATCH would claim the body is (or patches) a representation of a resource at that URL, but `/api/segments/unlock` serves no representation and cannot be GET. Contrast `PATCH /api/segments` `{segment, dhcp}`, which is correctly PATCH because its body carries the new field value. Do not "fix" these to PUT/PATCH.

---

## Development Commands

### Local Development Setup

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env: set MONGODB_URL, SITE_NETWORKS

# 4. Run
python main.py            # serves http://localhost:8000
```

### Required Environment Variables

```bash
MONGODB_URL="mongodb://localhost:27017"          # or mongodb+srv://... for Atlas — REQUIRED (fail-fast if unset)
MONGODB_DB_NAME="segments_manager"                    # optional, default: segments_manager
SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "bmc": "10.51.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "bmc": "10.52.0.0/16"}}'  # REQUIRED. JSON site topology; the single source of truth for
                                                    # configured sites; SITES is derived from its keys (no separate var)
API_TOKEN="<long-random-secret>"                   # REQUIRED (fail-fast) — Bearer token for write requests
```

> **This service triggers nothing.** It used to fire a best-effort `POST {WORKFLOWS_API_URL}/workflows/segment-connectivity` after every segment creation, which left the creation itself outside Temporal — invisible in the Temporal UI, and silently skipped whenever that call failed. **The direction is now reversed:** an operator POSTs the segment definition to the Cluster Orchestrator's workflow API, and the segment-connectivity workflow calls `POST /api/segments` here as its own first (durable, retried) step, then opens the firewall rules, then unlocks the segment — one Temporal run for the whole lifecycle. So `WORKFLOWS_API_URL` and `src/services/workflow_client.py` are gone, and this service is a plain dependency of that workflow. `POST /api/segments` and `POST /api/segments/bulk` still work exactly as before for direct use; they just create a `Locked` segment and nothing else happens to it.

> **API authentication.** `GET`/`HEAD` requests are open (the read-only web UI needs no auth). Every mutating request (`POST`/`PUT`/`PATCH`/`DELETE`) under `/api/*` must present the API token as `Authorization: Bearer <API_TOKEN>`. The token is the **only** credential — there is no username/password login, session, or cookie (all removed). Enforcement is centralized in one middleware in `src/app.py` (fail-closed — new write routes are protected automatically); there are no per-route auth dependencies. The token check (`verify_api_token`) uses a constant-time comparison.

### Testing

Integration tests in `tests/` run against a **live server** over HTTP (they skip
if it's unreachable, and clean up everything they create). See `tests/README.md`.

```bash
pip install pytest requests
pytest tests/ -v                                   # target http://127.0.0.1:8000
SEGMENTS_MANAGER_URL=http://host:8000 pytest tests/ -v # target elsewhere
```

The server under test must be configured with
`SITE_NETWORKS='{"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "bmc": "10.51.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "bmc": "10.52.0.0/16"}}'`. To test the container image, run a
throwaway MongoDB + the image on a shared podman network (see `tests/README.md`).

### Container Deployment (Podman)

```bash
./run.sh deploy      # build + start
./run.sh build|start|stop|restart|logs|status|test|clean
```

The project uses **Podman**, not Docker (all scripts use `podman`).

### Helm / Kubernetes

Chart in `deploy/helm/`. Set `mongodb.url` (stored in a generated Secret) or point at an existing secret via `mongodb.existingSecret`/`mongodb.existingSecretKey`. Non-sensitive config (`SITE_NETWORKS`, `MONGODB_DB_NAME`, server/log settings, `config.workflowsApiUrl`) is in a ConfigMap.

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│                Segments Manager                  │
│  API + Business Logic + Validation + Web UI  │
└───────────────────────┬──────────────────────┘
                        │ Motor (async)
                        ▼
┌─────────────────────────────────────────────┐
│                  MongoDB                     │
│      collection: segments (per-site)         │
└─────────────────────────────────────────────┘
```

### Key Architectural Decisions

1. **MongoDB backend** via Motor (`AsyncIOMotorClient`). No ORM — plain async collection calls.
2. **Clean Architecture** — distinct layers:
   - API (`src/api/routes.py`)
   - Services (`src/services/`)
   - Database utils (`src/utils/database/`) → Mongo layer (`src/database/`)
   - Models (`src/models/schemas.py`)
   - Validators (`src/utils/validators/`)
3. **Async throughout** — all I/O is `async`/`await` on Motor.
4. **Atomic allocation** — `allocate_segment()` uses `find_one_and_update(..., return_document=AFTER)` so concurrent callers can never receive the same segment.
5. **Short in-memory cache** — the full segments list is cached (60s TTL) with in-flight request de-duplication (`src/database/cache.py`); invalidated on every write.
6. **Fail-fast config** — missing `MONGODB_URL`, missing `API_TOKEN`, or an invalid `SITE_NETWORKS` crashes at startup. Invalid covers: unset, unparseable, a site with no `pool`, a non-strict or non-IPv4 CIDR, sites differing only by case, and pools that overlap each other or a BMC network. Setting the superseded `SITE_PREFIXES` while `SITE_NETWORKS` is unset also aborts — that combination means new code against a stale ConfigMap.
7. **No outbound calls** — this service talks to MongoDB and nothing else. The segment-connectivity orchestrator calls *in* (create, publish request ids, unlock); it is never called *from* here.

---

## Directory Structure

```
segments_2/
├── main.py                 # Entry point (delegates to src/run.py)
├── requirements.txt        # fastapi, uvicorn, pydantic, motor, pymongo, pandas, openpyxl, python-multipart
├── Dockerfile
├── .env.example
├── run.sh                  # Podman deployment script
│
├── src/
│   ├── run.py              # uvicorn startup
│   ├── app.py              # FastAPI app, lifespan (init/close storage), middleware, static
│   │
│   ├── api/routes.py       # All REST endpoints
│   ├── config/
│   │   ├── settings.py     # Env vars, site-prefix parsing & validation, logging
│   │   └── constants.py    # Cache TTLs, VLAN/subnet/field constraints, thresholds
│   │
│   ├── database/           # MongoDB layer
│   │   ├── __init__.py         # Public API: init/close_storage + segment ops
│   │   ├── mongo_client.py     # AsyncIOMotorClient init, get_db(), get_segments_collection()
│   │   ├── mongo_storage.py    # init_storage() (creates indexes) + close_storage()
│   │   ├── mongo_segments.py   # get/create/update/delete/allocate segment functions
│   │   ├── mongo_utils.py      # _doc_to_segment (ObjectId→str), _to_object_id (str→ObjectId, HTTP 400)
│   │   └── cache.py            # TTL cache + in-flight request coalescing
│   │
│   ├── models/schemas.py   # Pydantic models (extra="forbid" on request models)
│   │
│   ├── services/           # Business logic
│   │   ├── allocation_service.py   # allocate/release VLAN
│   │   ├── segment_service.py      # segment CRUD + bulk import
│   │   ├── stats_service.py        # statistics + health check (pings MongoDB)
│   │   ├── export_service.py       # CSV/Excel export
│   │   └── logs_service.py
│   │
│   └── utils/
│       ├── validators/          # input, network, organization validators
│       ├── database/            # DatabaseUtils facade over the Mongo layer
│       ├── error_handlers.py    # handle_db_errors, retry_on_network_error, db_operation
│       └── time_utils.py
│
├── static/                 # Web UI (html/css/js)
├── tests/                  # pytest integration tests
├── deploy/helm/            # Helm chart
└── deploy/scripts/         # Podman air-gap build/load scripts
```

---

## MongoDB Data Model

Collection: **`segments`**

```python
{
    "_id":          ObjectId,        # internal only — never part of the API surface
    "type":         str,             # "MCE" | "INVENTORY" | "HC" | "PXE", defaults to "HC"
    "site":         str,             # e.g. "site1"
    "vlan_id":      int,             # 1–4094
    "epg_name":     str,
    "segment":      str,             # CIDR, e.g. "192.168.1.0/24" — the natural key (unique + immutable)
    "dhcp":         bool,            # defaults to True on creation; the ONLY mutable field (PATCH /api/segments)
    "cluster_name": str | None,      # None = available; comma-separated for shared segments
    "allocated_at": datetime | None, # set on allocation; returned by the allocation API
    "status":       str,             # "Locked" | "Available" | "Allocated" — server-managed lifecycle,
                                     # the SOLE record of allocation state (the legacy `released` /
                                     # `released_at` pair was derivable from it and has been dropped;
                                     # init_storage() unsets it from existing documents)
    "segment_connectivity_requests": list[int] | None,  # pending firewall request ids shown in the UI beside status;
                                                # set/cleared by the segment-connectivity orchestrator
                                                # (PUT /api/segments/segment-connectivity-requests; empty list clears)
    "segment_connectivity_requests_submitted_at": datetime | None,  # when the pending ids were submitted;
                                                # drives the "time since submit" header in the UI popover;
                                                # cleared together with segment_connectivity_requests
}
```

> **`type` is one of `MCE`, `INVENTORY`, `HC`, `PXE`**, enforced by a Pydantic `Literal` (422 on any other value). Optional on create — defaults to `"HC"` if omitted. **Required** on `POST /api/segments/allocate`: the allocator must never guess which kind of segment a caller wants. (Release does *not* take it — the CIDR already determines the type.) It's a plain classifier with no lifecycle logic attached, unlike `status`.

> **Locked is the default status for new segments.** Lifecycle is one-way: `Locked → Available → Allocated → Available` — a segment can never become locked again via the API (no re-lock endpoint exists). It signals that firewall rules haven't been opened yet. `allocate_segment()` only considers segments with `status: "Available"`. An external service unlocks a segment via `POST /api/segments/unlock` with body `{"segment": "<cidr>"}` once provisioning is done.

> **Pending segment-connectivity request ids.** While waiting for firewall approval, the segment-connectivity orchestrator mirrors its still-pending request ids onto the segment via `PUT /api/segments/segment-connectivity-requests` (body `{"segment", "request_ids", "submitted_at"}`; `submitted_at` is optional, replace semantics, idempotent, empty list clears both fields — stored as `None`). The UI renders a **Requests ID** button beside the status badge whenever the list is non-empty; clicking it opens a popover anchored to the button. The popover header shows elapsed time since `submitted_at` ("Submitted N minutes ago", escalating to hours then days), followed by the pending ids. The display disappears automatically once the orchestrator sends the final empty update (all requests complete).

**Indexes** (created in `init_storage()`):
- `unique({site: 1, vlan_id: 1})` — one VLAN ID per site
- `unique({segment: 1})` — globally unique CIDR
- `{cluster_name: 1}` — allocation lookups
- `{site: 1}` — site filtering
- `{site: 1, type: 1, status: 1}` — the atomic allocator's selector (supersedes the old `{site, status}` index, which `init_storage()` drops)

**ObjectId rule**: `_id` is internal. Outbound segment dicts convert it via `str(...)` (`_doc_to_segment`), but the API never accepts an id — services resolve segments by their CIDR (`get_segment_by_segment`, 404 if unknown) and only then use the resolved `_id` for the Mongo write.

---

## Request Flow — Allocating a Segment

```
POST /api/segments/allocate  {cluster_name, site, type}
    ↓ routes.py → AllocationService.allocate_segment()
    ├─ validators: site, cluster_name
    ├─ DatabaseUtils.find_existing_allocation()  → idempotent per (cluster, site, type)
    └─ DatabaseUtils.find_and_allocate_segment() → allocate_segment() atomic find_one_and_update
    ↓
Return VLANAllocationResponse
```

---

## Validation Architecture

Defense-in-depth in `src/utils/validators/`:

- **input_validators.py** — site (must be in `SITES`), VLAN ID (1–4094), EPG name (≤64 chars, safe charset), cluster name.
- **network_validators.py** — CIDR format & strict network address, **site pool containment** (`get_site_pool(site)`, `network.subnet_of(pool)`), subnet mask /16–/31, reserved-range rejection, overlap detection.
- **organization_validators.py** — allocation state (can't delete allocated), **EPG-name uniqueness per site**.

VLAN uniqueness is enforced both at the app level (`check_vlan_exists(site, vlan_id)`) and by the Mongo unique index.

---

## Adding New Features

1. **Models** (`schemas.py`) — add Pydantic schema (keep `extra="forbid"` on request bodies).
2. **Validators** (`utils/validators/`) — add rules.
3. **Mongo layer** (`database/mongo_segments.py`) — add DB operations.
4. **DatabaseUtils** (`utils/database/`) — expose via the facade.
5. **Service** (`services/`) — business logic.
6. **Routes** (`api/routes.py`) — endpoint.
7. **Frontend** (`static/`) — UI if needed.

---

## Notes for Claude

1. **Production application** — emphasize reliability, validation, error handling.
2. **MongoDB is the source of truth** — all data ops go through the Motor layer in `src/database/`.
3. **No VRF, no external/centralized IPAM** — the app is decentralized and per-site. Do not reintroduce either concept.
4. **Fail-fast config** — `MONGODB_URL`, `API_TOKEN`, and a valid `SITE_NETWORKS` are required at startup. `SITES` is not a separate env var — it's derived from `SITE_NETWORKS`' keys.
5. **Async throughout** — everything touching the DB is `async`.
6. **Invalidate cache on writes** — call `invalidate_cache(CACHE_KEY_SEGMENTS)` after modifications (the Mongo write functions already do this).
7. **Wrap service methods** with `@handle_db_errors` + `@retry_on_network_error` + `@log_operation_timing` (or the combined `@db_operation`).
8. **Site pool containment** is a core validation rule: every segment must be a subnet of its site's configured `pool` (e.g. site1 ⇒ inside `192.10.0.0/16`). A segment equal to the whole pool is permitted.
9. **The segment CIDR is the API identifier** — single-segment endpoints are keyed by `segment` (query param for GET/DELETE, body field for writes), never by ObjectId. `_id` stays internal (str on the way out, resolved via CIDR lookup on the way in).

---

## Dependencies

**Python 3.11+**. Key packages (`requirements.txt`):
`fastapi`, `uvicorn[standard]`, `pydantic` (v2), `python-multipart`, `pandas`, `openpyxl`, `motor`, `pymongo`, `python-dotenv` (loads `.env` for local dev; real env vars take precedence), `httpx` (segment-connectivity workflow trigger).

`pytest` is used for tests (install separately if not present).

> Note: the pinned `pydantic`/`pandas` versions build cleanly on Python 3.11 (the container base). They do **not** build on Python 3.14 — use the container or a 3.11 venv for a faithful environment.

---

**Maintainer**: Segments Manager Team
