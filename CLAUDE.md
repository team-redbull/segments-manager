# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VLAN Manager** is a production-grade network VLAN allocation and management system. It provides an intelligent API layer and web UI for allocating VLAN segments to clusters across multiple sites, with comprehensive validation. Segments are stored in **MongoDB**.

**Type**: FastAPI Web Application + REST API
**Primary Language**: Python 3.11
**Architecture Pattern**: Clean Architecture with service-oriented design
**Storage Backend**: MongoDB (via Motor async driver)
**Deployment**: Containerized (Podman/Docker), Kubernetes/OpenShift ready (Helm chart)

> **Decentralized, per-site model.** There is **no VRF** and **no centralized IPAM**. VLAN IDs and EPG names are unique **per site**. The database enforces this with a unique compound index `{site, vlan_id}`.

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
# Edit .env: set MONGODB_URL, SITES, SITE_PREFIXES

# 4. Run
python main.py            # serves http://localhost:8000
```

### Required Environment Variables

```bash
MONGODB_URL="mongodb://localhost:27017"          # or mongodb+srv://... for Atlas — REQUIRED (fail-fast if unset)
MONGODB_DB_NAME="vlan_manager"                    # optional, default: vlan_manager
SITES="site1,site2,site3"                          # comma-separated site names
SITE_PREFIXES="site1:192,site2:193,site3:194"      # site:first-octet — every site in SITES MUST have an entry
```

### Testing

Integration tests in `tests/` run against a **live server** over HTTP (they skip
if it's unreachable, and clean up everything they create). See `tests/README.md`.

```bash
pip install pytest requests
pytest tests/ -v                                   # target http://127.0.0.1:8000
VLAN_MANAGER_URL=http://host:8000 pytest tests/ -v # target elsewhere
```

The server under test must be configured with `SITES=site1,site2,site3` and
`SITE_PREFIXES=site1:192,site2:193,site3:194`. To test the container image, run a
throwaway MongoDB + the image on a shared podman network (see `tests/README.md`).

### Container Deployment (Podman)

```bash
./run.sh deploy      # build + start
./run.sh build|start|stop|restart|logs|status|test|clean
```

The project uses **Podman**, not Docker (all scripts use `podman`).

### Helm / Kubernetes

Chart in `deploy/helm/`. Set `mongodb.url` (stored in a generated Secret) or point at an existing secret via `mongodb.existingSecret`/`mongodb.existingSecretKey`. Non-sensitive config (`SITES`, `SITE_PREFIXES`, `MONGODB_DB_NAME`, server/log settings) is in a ConfigMap.

---

## Architecture Overview

```
┌─────────────────────────────────────────────┐
│                VLAN Manager                  │
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
6. **Fail-fast config** — missing `MONGODB_URL`, or a site in `SITES` without a `SITE_PREFIXES` entry, crashes at startup.

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
    "_id":          ObjectId,        # returned to callers as str
    "site":         str,             # e.g. "site1"
    "vlan_id":      int,             # 1–4094
    "epg_name":     str,
    "segment":      str,             # CIDR, e.g. "192.168.1.0/24"
    "dhcp":         bool,
    "description":  str,
    "cluster_name": str | None,      # None = available; comma-separated for shared segments
    "allocated_at": datetime | None,
    "released":     bool,
    "released_at":  datetime | None,
}
```

**Indexes** (created in `init_storage()`):
- `unique({site: 1, vlan_id: 1})` — one VLAN ID per site
- `unique({segment: 1})` — globally unique CIDR
- `{cluster_name: 1}` — allocation lookups
- `{site: 1}` — site filtering

**ObjectId rule**: every outbound segment dict converts `_id` via `str(...)` (`_doc_to_segment`). Every inbound id converts back via `bson.ObjectId(...)` (`_to_object_id`), raising **HTTP 400** on malformed ids.

---

## Request Flow — Allocating a VLAN

```
POST /api/allocate-vlan  {cluster_name, site}
    ↓ routes.py → AllocationService.allocate_vlan()
    ├─ validators: site, cluster_name
    ├─ DatabaseUtils.find_existing_allocation()  → idempotent: returns existing allocation if any
    └─ DatabaseUtils.find_and_allocate_segment() → allocate_segment() atomic find_one_and_update
    ↓
Return VLANAllocationResponse
```

---

## Validation Architecture

Defense-in-depth in `src/utils/validators/`:

- **input_validators.py** — site (must be in `SITES`), VLAN ID (1–4094), EPG name (≤64 chars, safe charset), cluster name, description.
- **network_validators.py** — CIDR format & strict network address, **site IP-prefix enforcement** (`get_site_prefix(site)`), subnet mask /16–/31, reserved-range rejection, overlap detection.
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
4. **Fail-fast config** — `MONGODB_URL` and complete `SITE_PREFIXES` are required at startup.
5. **Async throughout** — everything touching the DB is `async`.
6. **Invalidate cache on writes** — call `invalidate_cache(CACHE_KEY_SEGMENTS)` after modifications (the Mongo write functions already do this).
7. **Wrap service methods** with `@handle_db_errors` + `@retry_on_network_error` + `@log_operation_timing` (or the combined `@db_operation`).
8. **Site IP prefixes** are a core validation rule (e.g. site1 ⇒ `192.x.x.x`).
9. **ObjectId handling** — str on the way out, `ObjectId` on the way in (HTTP 400 on bad format).

---

## Dependencies

**Python 3.11+**. Key packages (`requirements.txt`):
`fastapi`, `uvicorn[standard]`, `pydantic` (v2), `python-multipart`, `pandas`, `openpyxl`, `motor`, `pymongo`.

`pytest` is used for tests (install separately if not present).

> Note: the pinned `pydantic`/`pandas` versions build cleanly on Python 3.11 (the container base). They do **not** build on Python 3.14 — use the container or a 3.11 venv for a faithful environment.

---

**Maintainer**: VLAN Manager Team
