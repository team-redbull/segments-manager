# Codebase Structure

**Analysis Date:** 2026-03-27

## Directory Layout

```
segments_2/                        # Project root
├── main.py                       # Entry point (delegates to src/run.py)
├── requirements.txt              # Python dependencies (8 packages)
├── .env                          # Environment variables (git-ignored)
├── .env.example                  # Template for environment configuration
├── Dockerfile                    # Container image definition
├── README.md                     # User documentation
├── CLAUDE.md                     # Developer instructions (this project)
├── ARCHITECTURE.md               # System architecture documentation
├── run.sh                        # Podman deployment script
│
├── .planning/                    # GSD planning documents
│   └── codebase/                 # Analysis documents
│       ├── ARCHITECTURE.md
│       └── STRUCTURE.md
│
├── src/                          # Application source code
│   ├── run.py                   # Server startup (uvicorn entry)
│   ├── app.py                   # FastAPI app setup, lifespan, middleware
│   │
│   ├── api/                     # REST API endpoints
│   │   ├── __init__.py
│   │   └── routes.py            # All API endpoints (auth, segments, allocation, stats, export)
│   │
│   ├── auth/                    # Authentication & session management
│   │   ├── __init__.py
│   │   └── auth.py              # Session creation/validation, file persistence
│   │
│   ├── config/                  # Configuration and settings
│   │   ├── __init__.py
│   │   ├── settings.py          # Env vars, validation, logging setup
│   │   └── constants.py         # Application constants (optional)
│   │
│   ├── database/                # NetBox storage integration (9 modular files, 1,560 lines)
│   │   ├── __init__.py                    # Public API exports
│   │   ├── netbox_storage.py             # Main interface & initialization (~200 lines)
│   │   ├── netbox_client.py              # Client, executors, helpers (~139 lines)
│   │   ├── netbox_cache.py               # TTL-based caching & deduplication (~101 lines)
│   │   ├── netbox_helpers.py             # Object helpers: VRF, VLAN, Tenant, Role, Site (~360 lines)
│   │   ├── netbox_crud_ops.py            # Create/Update/Delete operations (~344 lines)
│   │   ├── netbox_query_ops.py           # Read & query operations (~198 lines)
│   │   ├── netbox_utils.py               # Utilities: safe access, conversion (~145 lines)
│   │   └── netbox_constants.py           # Centralized constants (~57 lines)
│   │
│   ├── models/                  # Data models (Pydantic schemas)
│   │   ├── __init__.py
│   │   └── schemas.py           # Request/response models (Segment, VLANAllocation, etc.)
│   │
│   ├── services/                # Business logic layer
│   │   ├── __init__.py
│   │   ├── allocation_service.py   # VLAN allocation & release logic
│   │   ├── segment_service.py      # Segment CRUD operations
│   │   ├── stats_service.py        # Statistics & health checks
│   │   ├── export_service.py       # CSV/Excel export
│   │   └── logs_service.py         # Log file access
│   │
│   └── utils/                   # Utility functions & helpers
│       ├── __init__.py
│       ├── database_utils.py            # Backward compatibility shim
│       ├── error_handlers.py            # Error translation, retry logic (~451 lines)
│       ├── logging_decorators.py        # Operation timing decorators
│       ├── time_utils.py                # Timezone utilities
│       │
│       ├── database/                    # Modular database utilities
│       │   ├── __init__.py              # DatabaseUtils facade aggregator
│       │   ├── allocation_utils.py      # Find/allocate/release segment logic
│       │   ├── segment_crud.py          # Create/read/update/delete segments
│       │   ├── segment_queries.py       # Search, filter, aggregate queries
│       │   └── statistics_utils.py      # Statistics calculations
│       │
│       └── validators/                  # Modular validation (5 modules)
│           ├── __init__.py              # Validators facade
│           ├── input_validators.py      # Site, VLAN ID, EPG name validation
│           ├── network_validators.py    # CIDR, subnet, reserved IPs validation
│           ├── data_validators.py       # Overlap, uniqueness, conflicts
│           ├── organization_validators.py  # VRF, tenant, role validation
│           └── security_validators.py   # XSS, injection prevention
│
├── static/                      # Web UI (served by FastAPI)
│   ├── html/
│   │   ├── index.html          # Main dashboard
│   │   └── help.html           # Help documentation
│   ├── css/
│   │   └── styles.css          # Dark/light theme support
│   └── js/
│       └── app.js              # Frontend JavaScript logic
│
├── tests/                       # Test suite (pytest)
│   ├── __init__.py
│   ├── test_api.py             # Integration tests (61KB, 80+ tests)
│   ├── test_comprehensive.py   # Edge case tests (80+ tests)
│   ├── test_vlan_allocation.py # VLAN allocation specific tests
│   ├── test_api_quick.py       # Quick smoke tests
│   ├── test_api_integration.py # Extended integration tests
│   ├── test_netbox_connection.py # Connection verification
│   └── README_TESTING.md       # Testing documentation
│
├── data/                        # Runtime data (git-ignored)
│   └── sessions.json           # Persistent session storage
│
├── logs/                        # Application logs (git-ignored)
│   └── segments_manager.log        # Rotating log file
│
├── deploy/                      # Deployment configurations
│   ├── helm/                   # Kubernetes Helm chart
│   │   └── templates/          # K8s manifests
│   └── scripts/                # Deployment scripts
│
├── docs/                        # Documentation
│   ├── API_REFERENCE.md        # Detailed API documentation
│   ├── DEPLOYMENT.md           # Deployment guide
│   └── TROUBLESHOOTING.md      # Troubleshooting guide
│
├── scripts/                     # Utility scripts
│   └── ...
│
└── sample_data/                 # Example data for testing
    └── ...
```

**Total Database Layer**: 1,560 lines across 9 focused modules

## Directory Purposes

**`src/api/`:**
- Purpose: HTTP API endpoint definitions
- Contains: FastAPI route handlers, request validation, authentication checks
- Key files: `routes.py` (150+ endpoints)

**`src/auth/`:**
- Purpose: Authentication and session management
- Contains: Session creation, validation, file persistence
- Key files: `auth.py` (session logic)

**`src/config/`:**
- Purpose: Application configuration and startup
- Contains: Environment variable parsing, validation, logging setup
- Key files: `settings.py` (configuration loading and fail-fast validation)

**`src/database/`:**
- Purpose: NetBox IPAM integration and data persistence
- Contains: 9 modular files for client, caching, CRUD, queries, helpers
- Key files:
  - `netbox_storage.py`: Main interface
  - `netbox_client.py`: Async executor setup
  - `netbox_cache.py`: Caching logic
  - `netbox_helpers.py`: Reference data resolution
  - `netbox_crud_ops.py`: Create/Update/Delete operations

**`src/models/`:**
- Purpose: Data structure definitions
- Contains: Pydantic models for request/response validation
- Key files: `schemas.py` (Segment, VLANAllocationRequest, VLANAllocationResponse, etc.)

**`src/services/`:**
- Purpose: Business logic orchestration
- Contains: Service classes coordinating database + validation
- Key files:
  - `allocation_service.py`: VLAN allocation/release
  - `segment_service.py`: Segment CRUD
  - `stats_service.py`: Statistics
  - `export_service.py`: CSV/Excel export

**`src/utils/database/`:**
- Purpose: Database operation utilities aggregated for services
- Contains: Allocation, CRUD, query, statistics utilities
- Pattern: DatabaseUtils facade aggregates these

**`src/utils/validators/`:**
- Purpose: Input validation in modular layers
- Contains: 5 validator classes (input, network, data, organization, security)
- Pattern: Validators facade aggregates these

**`src/utils/` (root):**
- Purpose: Cross-cutting utilities
- Contains: Error handling, logging decorators, time utilities
- Key files: `error_handlers.py`, `logging_decorators.py`, `time_utils.py`

**`static/`:**
- Purpose: Web UI assets
- Contains: HTML templates, CSS stylesheets, JavaScript logic
- Key files: `index.html` (main dashboard), `app.js` (frontend logic), `styles.css`

**`tests/`:**
- Purpose: Automated test suite
- Contains: Integration tests, edge case tests, smoke tests
- Key files: `test_api.py` (80+ tests), `test_comprehensive.py` (edge cases)

**`data/`:**
- Purpose: Runtime persistent data
- Contains: Session storage file
- Key files: `sessions.json` (survives restarts)

**`logs/`:**
- Purpose: Application logs
- Contains: Rotating log file
- Key files: `segments_manager.log`

## Key File Locations

**Entry Points:**
- `main.py`: Server startup (delegates to `src/run.py`)
- `src/run.py`: Uvicorn server initialization
- `src/app.py`: FastAPI application factory with lifespan setup

**Configuration:**
- `src/config/settings.py`: NetBox credentials, site config, logging, fail-fast validation
- `.env`: Runtime environment variables (git-ignored)
- `.env.example`: Template for environment setup

**Core Logic:**
- `src/api/routes.py`: All REST endpoint definitions (auth, allocation, segments, stats)
- `src/services/`: Business logic (allocation_service.py, segment_service.py, etc.)
- `src/database/netbox_storage.py`: Main database interface
- `src/utils/validators/`: Multi-layer validation logic

**Testing:**
- `tests/test_api.py`: Main integration test suite (80+ tests, 61KB)
- `tests/test_comprehensive.py`: Edge case coverage
- `tests/test_vlan_allocation.py`: VLAN allocation specific tests

## Naming Conventions

**Files:**
- Service files: `<function>_service.py` (e.g., `allocation_service.py`, `segment_service.py`)
- Database files: `netbox_<function>.py` (e.g., `netbox_crud_ops.py`, `netbox_cache.py`)
- Utility files: `<function>_utils.py` or `<function>.py` (e.g., `database_utils.py`, `time_utils.py`)
- Validator files: `<domain>_validators.py` (e.g., `network_validators.py`, `security_validators.py`)
- Test files: `test_<function>.py` (e.g., `test_api.py`, `test_comprehensive.py`)
- Models: Singular resource + schema (e.g., `Segment`, `VLANAllocationRequest`)

**Directories:**
- Lowercase, plural for collections: `src/services/`, `src/utils/`
- Lowercase, singular for features: `src/api/`, `src/auth/`, `src/config/`
- Lowercase, plural for test modules: `tests/`

**Classes:**
- PascalCase (e.g., `AllocationService`, `SegmentCRUD`, `InputValidators`)
- Facades: Plural or aggregator name (e.g., `DatabaseUtils`, `Validators`)

**Functions:**
- snake_case (e.g., `validate_site()`, `find_and_allocate_segment()`, `get_netbox_client()`)
- Async functions prefixed: `async def` (e.g., `async def allocate_vlan()`)
- Validation functions: `validate_<field>()` (e.g., `validate_site()`, `validate_segment_format()`)
- Getter functions: `get_<resource>()` (e.g., `get_cached()`, `get_netbox_client()`)

**Constants:**
- UPPERCASE_WITH_UNDERSCORES (e.g., `CACHE_KEY_PREFIXES`, `CACHE_TTL_MEDIUM`, `ROLE_DATA`)
- Grouped in `netbox_constants.py` (no magic strings throughout codebase)

**Variables:**
- snake_case (e.g., `cluster_name`, `allocated_segment`, `site_prefixes`)
- Private module variables: `_prefix` (e.g., `_netbox_client`, `_cache`, `_inflight_requests`)
- Cache keys: `CACHE_KEY_<RESOURCE>` (e.g., `CACHE_KEY_PREFIXES`, `CACHE_KEY_VLANS`)

## Where to Add New Code

**New Feature (e.g., VLAN tagging support):**
- Models: Add field to `src/models/schemas.py` (e.g., `tags: List[str]`)
- Validation: Add to appropriate `src/utils/validators/<domain>_validators.py` (e.g., `security_validators.py` for tag format)
- Service: Extend existing service in `src/services/` (e.g., `segment_service.py`)
- Database: Add query/operation to `src/database/netbox_<function>.py` (e.g., `netbox_helpers.py` for tag helpers)
- Routes: Add endpoint to `src/api/routes.py`
- Tests: Add test to `tests/test_api.py` or new `tests/test_<feature>.py`

**New Validation Rule:**
- Location: Create/extend appropriate validator file in `src/utils/validators/`
  - Input/basic checks: `input_validators.py`
  - Network validation: `network_validators.py`
  - Data conflicts: `data_validators.py`
  - Organization checks: `organization_validators.py`
  - Security (XSS, injection): `security_validators.py`
- Pattern:
  ```python
  @staticmethod
  def validate_<field>(value: str) -> None:
      if not valid_condition:
          raise HTTPException(status_code=400, detail="Error message")
  ```
- Usage: Call from service via `Validators.validate_<field>()`

**New Service:**
- Location: Create `src/services/<name>_service.py`
- Pattern: Static methods with decorators for concerns
  ```python
  class MyService:
      @staticmethod
      @handle_netbox_errors
      @retry_on_network_error(max_retries=3)
      @log_operation_timing("operation_name", threshold_ms=1000)
      async def my_operation(input_data):
          # Validation
          Validators.validate_<field>(input_data.field)
          # Business logic
          # Database operation
          result = await DatabaseUtils.<operation>(...)
          return result
  ```
- Register in: `src/api/routes.py` as new endpoint

**New Database Operation:**
- For queries: Extend `src/utils/database/segment_queries.py` or add to `src/database/netbox_query_ops.py`
- For CRUD: Extend `src/utils/database/segment_crud.py` or add to `src/database/netbox_crud_ops.py`
- For helpers: Extend `src/database/netbox_helpers.py`
- Aggregate in: `src/utils/database/__init__.py` (DatabaseUtils facade)
- Usage pattern:
  ```python
  # In database operation
  @log_netbox_timing("operation_name")
  async def my_operation(...):
      nb = get_netbox_client()
      executor = get_netbox_<read|write>_executor()
      result = await run_netbox_<get|write>(lambda: nb.<api>.<method>(...), "description")
      return result
  ```

**New Endpoint:**
- Location: `src/api/routes.py`
- Pattern:
  ```python
  @router.post("/my-endpoint")
  async def my_endpoint(
      request: MyRequest,
      _: bool = Depends(require_auth)  # If write operation
  ):
      """Endpoint description"""
      return await MyService.my_operation(request)
  ```
- Add Pydantic model to `src/models/schemas.py` if needed

**Utilities (Helpers):**
- Shared helpers: `src/utils/` (e.g., `error_handlers.py`, `logging_decorators.py`)
- Database helpers: `src/database/netbox_utils.py`
- Time helpers: `src/utils/time_utils.py`

## Special Directories

**`data/`:**
- Purpose: Runtime persistent data (not git-tracked)
- Generated: Yes (created if doesn't exist)
- Committed: No (in .gitignore)
- Contents: `sessions.json` (survives server restarts)

**`logs/`:**
- Purpose: Application logs (not git-tracked)
- Generated: Yes (created on first run)
- Committed: No (in .gitignore)
- Contents: `segments_manager.log` (rotating daily)

**`deploy/helm/`:**
- Purpose: Kubernetes Helm chart for production deployment
- Generated: No (committed to repo)
- Contents: K8s manifests, values.yaml, Chart.yaml
- Usage: `helm install segments-manager ./deploy/helm/`

**`static/`:**
- Purpose: Web UI assets (committed to repo)
- Generated: No
- Contents: HTML templates, CSS, JavaScript
- Served by: FastAPI static file mounting at `/static`

**`.venv/`:**
- Purpose: Python virtual environment (not git-tracked)
- Generated: Yes (by `python -m venv .venv`)
- Committed: No (in .gitignore)
- Usage: `source .venv/bin/activate`

**`.planning/codebase/`:**
- Purpose: GSD analysis documents (committed to repo)
- Generated: By `/gsd:map-codebase` command
- Contents: ARCHITECTURE.md, STRUCTURE.md, etc.

---

*Structure analysis: 2026-03-27*
