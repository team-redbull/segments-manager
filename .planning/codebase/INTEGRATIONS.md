# External Integrations

**Analysis Date:** 2026-03-27

## APIs & External Services

**NetBox IPAM (Primary Integration):**
- NetBox - Network IP Address Management system
  - SDK/Client: pynetbox 7.3.3
  - Auth: `NETBOX_TOKEN` environment variable (Bearer token)
  - Endpoint: `NETBOX_URL` environment variable
  - SSL: Configurable via `NETBOX_SSL_VERIFY` (default: true)
  - Purpose: All VLAN and IP prefix (segment) data storage and retrieval
  - Location: `src/database/netbox_*.py` modules
  - Operations: Full CRUD on VLANs, Prefixes, Sites, VRFs, Tenants

**Request Flow:**
```
App → pynetbox (Python library) → NetBox REST API → PostgreSQL
```

## Data Storage

**Primary Database:**
- NetBox IPAM (PostgreSQL backend)
  - Connection: Via NetBox REST API (not direct database connection)
  - Client: pynetbox 7.3.3
  - Auth: API token via `NETBOX_TOKEN`
  - Data: VLANs, IP Prefixes (segments), Sites, VRFs, Tenants, custom fields

**Data Mapping:**
| Segments Manager Concept | NetBox Object | Storage |
|---------------------|---------------|---------|
| Segment | IP Prefix | dcim.prefixes |
| VLAN ID | VLAN | ipam.vlans |
| Site | Site Group | dcim.site_groups |
| EPG Name | VLAN Name | ipam.vlans.name |
| Cluster Allocation | Custom Field "cluster" | ipam.prefixes.custom_fields |
| VRF | VRF | ipam.vrfs |
| DHCP | Custom Field "dhcp" | ipam.prefixes.custom_fields |
| Description | Comments | ipam.prefixes.description |

**Local File Storage:**
- Session persistence: `data/sessions.json`
  - Location: `src/auth/auth.py`
  - Format: JSON with session tokens, expiry timestamps
  - Persistence: File-based across restarts
  - TTL: 7 days rolling window (extends on each request)
  - Created at: `SESSION_FILE = Path("data/sessions.json")`

**Caching:**
- In-memory TTL cache (Python dict)
  - Location: `src/database/netbox_cache.py`
  - TTL settings:
    - Static data (VRF, Tenant, Role, Site): 3600s (1 hour)
    - Dynamic data (Prefixes, VLANs): 600s (10 minutes)
  - Request coalescing: Prevents concurrent duplicate API calls
  - Cache key format: Simple string keys like "vlan_100_site1"

## Authentication & Identity

**Web UI Authentication:**
- Custom session-based authentication
  - Location: `src/auth/auth.py`
  - Methods:
    1. Session cookie (web browser)
    2. HTTP Basic Auth (curl -u username:password)
  - Credentials: `AUTH_USERNAME` and `AUTH_PASSWORD` environment variables
  - Session storage: `data/sessions.json` (persistent)
  - Session TTL: 7 days with rolling window

**API Authentication:**
- Session token as Bearer token (for non-browser clients)
- HTTP Basic Auth support for curl and CLI tools
- No OAuth, no external auth provider integration

**NetBox API Authentication:**
- Bearer token authentication
  - Token: `NETBOX_TOKEN` environment variable
  - Header: `Authorization: Token {NETBOX_TOKEN}`
  - Generated in NetBox UI: User Menu → API Tokens
  - Permissions: Read-only and write operations (depends on token scopes)
  - SSL: Configurable verification (supports self-signed certificates)

## Monitoring & Observability

**Error Tracking:**
- None configured (no Sentry, DataDog, etc.)
- Errors logged to `segments_manager.log` and stdout

**Logs:**
- File-based rotating logs
  - File: `segments_manager.log`
  - Handler: RotatingFileHandler (50MB per file, 5 backups)
  - Location: `src/config/settings.py`
- Console/stdout output for container logs
- NetBox operation timing: Logged for operations >2 seconds
  - Location: `src/database/netbox_client.py::log_netbox_timing()`

**Health Check:**
- Endpoint: `GET /api/health`
- Used by: Docker/Kubernetes health checks
- Response: Simple HTTP 200 (container heartbeat)
- Interval: 30 seconds (Dockerfile healthcheck)

## CI/CD & Deployment

**Hosting:**
- Containerized: Podman or Docker
- Kubernetes/OpenShift ready
- No managed hosting provider integration (self-hosted)

**CI Pipeline:**
- GitHub Actions (`.github/workflows/build.yml`)
- Triggered on: Push to main branch
- Steps:
  1. Checkout code (fetch-depth: 0 for full history)
  2. Generate version: Semantic versioning from git tags
  3. Log in to Docker Hub (secrets: DOCKER_USERNAME, DOCKER_PASSWORD)
  4. Build Docker image (multi-tag: version + latest)
  5. Push to Docker Hub

**Deployment Options:**
- Manual: `./run.sh deploy` (Podman script)
- Docker compose: Available in deploy/ directory
- Helm chart: Available in deploy/helm/
- Manual podman commands: Documented in CLAUDE.md

## Environment Configuration

**Required env vars:**
- `NETBOX_URL` - NetBox instance URL (must be reachable)
- `NETBOX_TOKEN` - API token with appropriate permissions
- `SITES` - Comma-separated site names (must exist in NetBox)
- `NETWORK_SITE_PREFIXES` or `SITE_PREFIXES` - IP prefix mapping (CRITICAL)

**Optional env vars:**
- `NETBOX_SSL_VERIFY` - SSL verification (default: true)
- `SERVER_HOST` - Bind address (default: 0.0.0.0)
- `SERVER_PORT` - Port (default: 8000)
- `LOG_LEVEL` - Log level (default: INFO)
- `AUTH_USERNAME` - Web UI username (default: admin)
- `AUTH_PASSWORD` - Web UI password (default: admin)

**Secrets location:**
- Environment variables (container: via -e or --env-file)
- `.env` file (development only)
- No secrets vault integration (e.g., HashiCorp Vault, AWS Secrets Manager)

**Startup Validation:**
- Fail-fast: Missing env vars crash application at startup
- Configuration validation: `validate_site_prefixes()` in `src/config/settings.py`
- NetBox connection test: Attempted during `init_storage()` in `src/app.py`

## Webhooks & Callbacks

**Incoming:**
- None detected - No webhook receiving endpoints

**Outgoing:**
- None detected - Application does not send webhooks
- NetBox is read-only for reference data (Site Groups, VRFs, Roles)
- NetBox write operations are synchronous direct API calls

**Synchronization:**
- One-way: App reads from NetBox, writes to NetBox
- No event-driven integrations
- No callback handlers for external services

## Data Export

**Formats:**
- CSV export via pandas
  - Endpoint: `GET /api/export/segments/csv`
  - Fields: Site, VRF, VLAN ID, EPG Name, Segment, DHCP, Description, Cluster Name, Status
  - Filters: Optional site and allocated status
  - Location: `src/services/export_service.py`

- Excel export via openpyxl + pandas
  - Endpoint: `GET /api/export/segments/excel`
  - Features: Auto-fit column widths, formatted sheet name
  - Filters: Optional site and allocated status
  - Location: `src/services/export_service.py`

- Statistics CSV export
  - Endpoint: `GET /api/export/stats/csv`
  - Data: Per-site allocation statistics
  - Location: `src/services/export_service.py`

## Network Architecture

**Connectivity:**
- Outbound: HTTPS to NetBox instance (pynetbox handles)
- Inbound: HTTP on port 8000 (or configured SERVER_PORT)
- SSL/TLS: Only for NetBox connection (configurable)
- CORS: Enabled for all origins (allow_origins=["*"])

**Thread Pools:**
- Read pool: 30 workers for GET requests to NetBox
- Write pool: 20 workers for POST/PUT/DELETE requests
- Location: `src/database/netbox_client.py`

**Rate Limiting:**
- NetBox Cloud has aggressive rate limiting
- Mitigation: 10-minute cache TTL for dynamic data
- Request coalescing: Prevents concurrent duplicate fetches
- Location: `src/database/netbox_cache.py`

---

*Integration audit: 2026-03-27*
