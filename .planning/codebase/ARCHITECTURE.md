# Architecture

**Analysis Date:** 2026-03-27

## Pattern Overview

**Overall:** Clean Architecture with Layered Service-Oriented Design

**Key Characteristics:**
- Strict separation of concerns across API, Service, Database, and Validation layers
- Asynchronous throughout using Python async/await with thread pool executors
- NetBox as the single source of truth for IPAM data (REST API backend via pynetbox)
- Fail-fast configuration validation at startup
- Aggressive caching (TTL-based with in-flight request deduplication) to optimize NetBox API usage
- Decorator-based cross-cutting concerns (error handling, retries, timing, validation)

## Layers

**Presentation Layer:**
- Purpose: HTTP API endpoints and static web UI
- Location: `src/api/routes.py`, `static/` (HTML/CSS/JS)
- Contains: FastAPI route handlers, request/response models, authentication middleware
- Depends on: Service layer, authentication module
- Used by: HTTP clients, web browsers

**Service Layer:**
- Purpose: Business logic orchestration and validation application
- Location: `src/services/`
- Contains: `allocation_service.py` (VLAN allocation), `segment_service.py` (segment CRUD), `stats_service.py` (statistics), `export_service.py` (CSV/Excel), `logs_service.py` (log access)
- Depends on: DatabaseUtils, Validators, error handlers, logging decorators
- Used by: API routes

**Database Access Layer:**
- Purpose: NetBox IPAM integration and data persistence abstraction
- Location: `src/database/` (9 modular files) and `src/utils/database/` (utility aggregators)
- Contains:
  - `netbox_client.py`: Client initialization, thread pool executors (30 readers / 20 writers), async execution helpers
  - `netbox_cache.py`: TTL-based caching (10min for dynamic, 1hr for static), in-flight request deduplication
  - `netbox_helpers.py`: VRF/VLAN/Tenant/Role/Site resolution and creation
  - `netbox_crud_ops.py`: Create/Update/Delete segment operations
  - `netbox_query_ops.py`: Read and query operations with filtering
  - `netbox_utils.py`: Safe attribute access, data conversion (prefix ↔ segment)
  - `netbox_constants.py`: Centralized constants (no magic strings)
  - `netbox_storage.py`: Main interface, initialization, reference data prefetching
- Depends on: pynetbox library, configuration
- Used by: Services, validators

**Utilities & Cross-Cutting Concerns:**
- Location: `src/utils/`
- Components:
  - `validators/`: Modular validation (input, network, organization, data security)
  - `error_handlers.py`: NetBox error translation, retry logic with exponential backoff, exception handling
  - `logging_decorators.py`: Operation timing, performance monitoring
  - `time_utils.py`: Timezone utilities
  - `database_utils.py`: Backward compatibility shim aggregating `src/utils/database/` utilities
- Used by: All layers

**Authentication & Security:**
- Purpose: Session management, user authentication
- Location: `src/auth/auth.py`
- Contains: Session creation/validation, file-based session persistence, TTL-based expiry
- Depends on: Configuration (AUTH_USERNAME, AUTH_PASSWORD)
- Used by: API routes via `require_auth()` and `get_current_user()` dependencies

**Configuration & Setup:**
- Purpose: Environment parsing, logging configuration, startup validation
- Location: `src/config/settings.py`
- Contains: NetBox credentials, site configuration, IP prefix validation, logging setup
- Used by: All layers during initialization

## Data Flow

**VLAN Allocation Flow:**

1. HTTP POST `/api/allocate-vlan` → `routes.py`
2. `routes.py` → `AllocationService.allocate_vlan()`
3. Service validates inputs:
   - `Validators.validate_site()`, `validate_cluster_name()`, `validate_vrf()` (sync/async)
4. Check for existing allocation:
   - `DatabaseUtils.find_existing_allocation()` → `AllocationUtils.find_existing_allocation()`
   - Calls `netbox_query_ops.find_prefixes_with_cluster()` (cached)
   - Returns if exists (idempotent)
5. If not allocated, atomically find and allocate:
   - `DatabaseUtils.find_and_allocate_segment()` → `AllocationUtils.find_and_allocate_segment()`
   - Query available segments: `netbox_query_ops.find_available_segments()` (filtered, cached)
   - Update allocation atomically: `netbox_crud_ops.update_prefix_cluster()` (write, cache invalidated)
   - Cache invalidation: `invalidate_cache(CACHE_KEY_PREFIXES)`
6. Return `VLANAllocationResponse` with allocated segment details

**Segment Creation Flow:**

1. HTTP POST `/api/segments` with Segment model
2. `SegmentService.create_segment()` validates:
   - Input validation: site, VLAN ID, EPG name, cluster name (sync)
   - Network validation: CIDR format, site IP prefix match, subnet mask /16-/29, reserved IP check
   - Conflict validation: IP overlap detection, EPG name uniqueness per site/VRF/VLAN
   - Security: XSS injection prevention in description/EPG
   - VRF validation: VRF exists in NetBox (async)
3. Create in NetBox:
   - `DatabaseUtils.create_segment()` → `SegmentCRUD.create_segment()`
   - Resolve VRF, Site Group, Tenant, Role (cached helpers)
   - Create VLAN Group (if needed): `netbox_helpers.get_or_create_vlan_group()`
   - Create VLAN: `netbox_crud_ops.create_vlan()`
   - Create prefix (segment): `netbox_crud_ops.create_prefix()`
   - Set custom fields: cluster (if allocated), dhcp
4. Cache invalidation on write
5. Return created segment

**Query with Caching:**

1. Request arrives: `GET /api/segments?site=site1&allocated=true`
2. Check cache: `get_cached(CACHE_KEY_PREFIXES)`
   - Cache HIT (< 10min old): Return cached data, apply filters in memory
   - Cache MISS or EXPIRED: Proceed to fetch
3. Check in-flight: `get_inflight_request(CACHE_KEY_PREFIXES)`
   - In-flight request exists: Await same task (deduplication)
   - No in-flight: Create task, register in `_inflight_requests`
4. Fetch from NetBox:
   - `netbox_query_ops.find_all_prefixes()` via `run_netbox_get()` (thread pool executor)
   - Parallel helper lookups: VRF, Site, Tenant, Role (via cached `get_cached()`)
5. Cache result: `set_cache(CACHE_KEY_PREFIXES, data, ttl=600)`
6. Apply filters, return

**Error Handling & Resilience:**

1. All operations decorated with:
   - `@handle_netbox_errors`: Translate NetBox/pynetbox exceptions → HTTPException (400-504)
   - `@retry_on_network_error(max_retries=3)`: Exponential backoff (1s → 2s → 4s) on network failures
   - `@log_operation_timing()`: Log slow operations > 2000ms
2. Exception chain:
   - NetBox RequestError → HTTP 400/403/404/500 with clear message
   - Network timeout → HTTP 504 with retry info
   - Validation error → HTTP 400 with field details
   - Concurrent modification → HTTP 409 with refresh instruction

**State Management:**

- **Segments (VLAN + Prefix):** NetBox IPAM (source of truth)
  - VLAN: ID, Name (EPG), Group, Tenant, Role
  - Prefix (segment): CIDR, VRF, Site Group, Status (active=available, reserved=allocated), Tenant, Role
  - Custom Fields: `cluster` (cluster name or null), `dhcp` (bool)
  - Timestamps: `created`, `last_updated` (managed by NetBox)
- **Sessions:** File-based JSON persistence in `data/sessions.json`
  - Session token → {username, expires_at, created_at}
  - Cleaned on startup (expired sessions removed)
  - TTL: 7 days
- **Cache:** In-memory dictionary with TTL
  - Prefixes/VLANs: 10min TTL (dynamic data)
  - VRFs/Tenant/Roles/Sites: 1hr TTL (static reference data)
  - Invalidated on any write operation

## Key Abstractions

**NetBoxStorage:**
- Purpose: Provides unified storage interface abstracting away pynetbox complexity
- Location: `src/database/netbox_storage.py`, `src/database/netbox_client.py`
- Pattern: Repository pattern with async wrapper
- Initialization: `init_storage()` verifies NetBox connection, prefetches reference data
- Shutdown: `close_storage()` releases executor resources

**DatabaseUtils (Facade):**
- Purpose: Aggregates database operations across specialized utility modules
- Location: `src/utils/database/__init__.py` (aggregates), actual implementations in `allocation_utils.py`, `segment_crud.py`, `segment_queries.py`, `statistics_utils.py`
- Pattern: Static facade with delegates
- Example: `DatabaseUtils.find_existing_allocation()` → `AllocationUtils.find_existing_allocation()`

**Validators (Modular Chain):**
- Purpose: Layered validation with clear responsibility separation
- Location: `src/utils/validators/` (5 modules)
  - `input_validators.py`: Site, VLAN ID, EPG name, cluster name, description basic checks
  - `network_validators.py`: CIDR format, subnet mask, reserved IPs, network/broadcast/gateway
  - `data_validators.py`: IP overlap, VLAN name uniqueness, schema validation
  - `organization_validators.py`: VRF existence, tenant, roles
  - `security_validators.py`: XSS injection prevention
- Pattern: Static method chain, fail-fast (raise HTTPException on first failure)

**Service Classes:**
- Purpose: Encapsulate business logic, coordinate database and validation
- Location: `src/services/`
- Pattern: Static methods (stateless), decorators for concerns
- Example: `SegmentService.create_segment()` chains validation → database → cache invalidation

**Thread Pool Executors:**
- Purpose: Prevent blocking event loop during sync NetBox API calls
- Location: `src/database/netbox_client.py`
- Pattern: Two separate pools for reads vs writes
  - Read executor: 30 workers (high concurrency for GET)
  - Write executor: 20 workers (lower concurrency for POST/PUT/DELETE)
- Usage: `await loop.run_in_executor(executor, blocking_function)`

**Caching with Request Coalescing:**
- Purpose: Reduce NetBox API calls and network traffic
- Location: `src/database/netbox_cache.py`
- Pattern: TTL-based in-memory cache + in-flight request deduplication
- Example: If 100 concurrent requests for same prefix list arrive:
  - Request 1: Cache miss → fetch from NetBox, register task
  - Requests 2-100: Detect in-flight task → await same result (no duplicate API calls)
  - All 100 receive cached result after single NetBox call

## Entry Points

**HTTP Server:**
- Location: `main.py` → `src/run.py` → `src/app.py`
- Triggers: Server startup (`python main.py` or `uvicorn src.app:app`)
- Responsibilities:
  1. Initialize session storage (load from `data/sessions.json`)
  2. Validate site prefixes (fail-fast on misconfiguration)
  3. Initialize NetBox storage (verify connection, prefetch reference data)
  4. Start uvicorn ASGI server on `SERVER_HOST:SERVER_PORT`

**FastAPI Application:**
- Location: `src/app.py`
- Pattern: Lifespan context manager for async startup/shutdown
- Setup:
  - CORS middleware (allow all origins)
  - Static file mounting with cache headers (1yr for assets, 1hr for HTML)
  - API router registration at `/api` prefix
  - Root HTML endpoint `GET /` serves `static/html/index.html`

**API Router:**
- Location: `src/api/routes.py`
- Authentication: All write endpoints require `require_auth()` dependency
- Endpoints:
  - Auth: POST `/api/auth/login`, POST `/api/auth/logout`, GET `/api/auth/status`
  - Allocation: POST `/api/allocate-vlan`, POST `/api/release-vlan`
  - Segments: GET/POST/PUT/DELETE `/api/segments`, GET `/api/segments/search`
  - Bulk: POST `/api/segments/bulk` (CSV import)
  - Stats: GET `/api/sites`, GET `/api/stats`, GET `/api/health`
  - Export: GET `/api/export/csv`, GET `/api/export/excel`

## Error Handling

**Strategy:** Transparent translation of NetBox API errors to clear HTTP responses

**Patterns:**

1. **Decorator-based error handling:**
   ```python
   @handle_netbox_errors  # Outermost (catches all exceptions)
   @retry_on_network_error(max_retries=3)  # Middle (retries on network errors)
   @log_operation_timing()  # Innermost (times the operation)
   async def allocate_vlan(request):
       ...
   ```

2. **Error categorization:**
   - Validation errors (400): Invalid site, VLAN ID, network format, IP overlap
   - Not found (404): Resource missing in NetBox
   - Forbidden (403): API token lacks permissions
   - Unauthorized (401): API token invalid/expired
   - Conflict (409): Concurrent modification detected
   - Service unavailable (503): NetBox unreachable
   - Timeout (504): NetBox slow to respond
   - Server error (500): Unexpected exception

3. **Retry strategy:**
   - Network errors (connection refused, timeout, connection reset): Retry with exponential backoff
   - HTTP 5xx: Retry
   - HTTP 4xx (validation, auth): No retry (pass immediately)
   - Custom exceptions: No retry (pass immediately)

4. **Logging:**
   - ERROR level: Failures, validation violations, NetBox errors
   - WARNING level: Network retries, slow operations (>2s)
   - DEBUG level: Cache hits/misses, operation details
   - INFO level: Startup, major operations (allocation, release)

## Cross-Cutting Concerns

**Logging:** Structured logging with module-level loggers
- Logger initialization: `setup_logging()` in `src/config/settings.py`
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- File output: `segments_manager.log` (rotating)
- Level: Configurable via `LOG_LEVEL` env var (default: INFO)

**Validation:** Multi-layer defense with early fail-fast
- Input validation: User-provided data (site, VLAN ID, etc.)
- Network validation: CIDR correctness, IP range safety
- Business logic validation: Uniqueness, conflicts, allocation state
- Security validation: XSS injection, script injection prevention

**Authentication:** Session-based with file persistence
- Session creation: `login()` generates 32-byte secure token
- Session storage: JSON file in `data/sessions.json` (survives restarts)
- Session validation: `get_current_user()` dependency checks cookie or Bearer token
- Session expiry: 7 days from creation or last activity
- Credentials: `AUTH_USERNAME` and `AUTH_PASSWORD` env vars (default: admin/admin)

**Performance Monitoring:** Built-in timing and slow operation detection
- Decorator: `@log_operation_timing("operation_name", threshold_ms=2000)`
- Logs operation duration only if exceeds threshold (reduces noise)
- Examples:
  - Slow allocation (>2s): Likely NetBox Cloud throttling
  - Slow cache miss (>200ms): Network latency to NetBox
  - Fast cache hit (<1ms): In-memory lookup

**Resource Cleanup:** Graceful shutdown and connection management
- Executor shutdown: Thread pool executors cleaned up on server shutdown
- NetBox client: Singleton pattern with explicit close
- File handles: Context managers ensure proper cleanup
- Cache: In-memory dictionary (auto-collected on app shutdown)

---

*Architecture analysis: 2026-03-27*
