# Technology Stack

**Analysis Date:** 2026-03-27

## Languages

**Primary:**
- Python 3.11 - All application code, API, and services

**Secondary:**
- JavaScript (ES6) - Web UI frontend in `static/js/app.js`
- HTML5 - Static pages in `static/html/`
- CSS3 - Styling in `static/css/styles.css`

## Runtime

**Environment:**
- Python 3.11 slim (container uses `python:3.11-slim` base image)

**Package Manager:**
- pip - Python dependency management
- Lockfile: Not explicitly present (uses fixed versions in `requirements.txt`)

## Frameworks

**Core:**
- FastAPI 0.104.1 - Web framework and REST API server (`src/app.py`)
- uvicorn[standard] 0.24.0 - ASGI server for FastAPI (`src/run.py`)

**Data Validation & Serialization:**
- pydantic 2.5.0 - Data validation, type hints, and schema generation (`src/models/schemas.py`)

**Data Processing & Export:**
- pandas 2.1.4 - CSV and data manipulation (`src/services/export_service.py`)
- openpyxl 3.1.2 - Excel export engine for pandas

**HTTP & Integration:**
- pynetbox 7.3.3 - NetBox REST API client wrapper (`src/database/netbox_client.py`)
- requests 2.31.0 - HTTP client for external APIs

**File Handling:**
- python-multipart 0.0.6 - Multipart form data parsing

## Key Dependencies

**Critical:**
- pynetbox 7.3.3 - NetBox IPAM integration (primary data source)
  - Provides Python bindings to NetBox REST API
  - Used for all VLAN and segment operations
  - Location: `src/database/netbox_*.py` modules

- pydantic 2.5.0 - Request/response validation
  - Validates all API inputs with type safety
  - Location: `src/models/schemas.py`

**Infrastructure:**
- pandas 2.1.4 - Data export to CSV format
  - Converts segment/statistics data to tabular format
  - Location: `src/services/export_service.py`

- requests 2.31.0 - HTTP client for concurrent operations
  - Used by pynetbox under the hood
  - Supports custom headers, SSL verification control

## Configuration

**Environment:**
- Loaded from `.env` file via `os.getenv()` in `src/config/settings.py`
- Environment variables validated at application startup (fail-fast)
- No support for `.env` parser library (uses raw `os.getenv()`)

**Key Configuration Files:**
- `.env.example` - Template for all required environment variables
- `Dockerfile` - Container image definition with Python 3.11 slim base
- `.github/workflows/build.yml` - CI/CD pipeline for Docker image builds

**Required Environment Variables:**
- `NETBOX_URL` - NetBox instance URL (CRITICAL)
- `NETBOX_TOKEN` - NetBox API authentication token (CRITICAL)
- `NETBOX_SSL_VERIFY` - SSL verification (default: "true")
- `SITES` - Comma-separated site names (default: "site1,site2,site3")
- `NETWORK_SITE_PREFIXES` - Multi-network site IP prefix mapping (new format)
- `SITE_PREFIXES` - Legacy single-network site IP prefix mapping (deprecated)
- `SERVER_HOST` - Server bind address (default: "0.0.0.0")
- `SERVER_PORT` - Server port (default: 8000)
- `LOG_LEVEL` - Logging level (default: "INFO")
- `AUTH_USERNAME` - Web UI login username (default: "admin")
- `AUTH_PASSWORD` - Web UI login password (default: "admin")

**Build:**
- `Dockerfile` - Multi-stage capable, includes:
  - Python 3.11-slim base image
  - System dependencies: curl (for health check)
  - Data directory: `/app/data` (volume mount point)
  - Health check: HTTP GET to `/api/health` every 30 seconds
  - Entrypoint: `python main.py`

## Platform Requirements

**Development:**
- Python 3.11+
- Virtual environment recommended
- pip for dependency installation

**Production:**
- Containerized deployment via Podman or Docker
- Kubernetes/OpenShift compatible
- Volume mount for persistent session storage: `/app/data`
- Network access to NetBox instance
- Health check endpoint: `/api/health`

**Container Specs:**
- Image: `python:3.11-slim`
- Port: 8000
- Volume: `/app/data` (for session persistence)
- Memory: Minimal (Python 3.11-slim is lightweight)
- CPU: No special requirements

## Threading & Concurrency

**Thread Pools:**
- Read executor (GET operations) - 30 workers (`src/database/netbox_client.py`)
- Write executor (POST/PUT/DELETE operations) - 20 workers
- Used for blocking I/O to NetBox API without blocking async event loop

**Async/Await:**
- All I/O operations are async via asyncio
- NetBox calls wrapped in `loop.run_in_executor()`
- Location: `src/database/netbox_client.py`

## Logging

**Framework:** Python's `logging` module

**Configuration:**
- Configured in `src/config/settings.py::setup_logging()`
- Rotating file handler: 50MB per file, keeps 5 backups
- Log file: `segments_manager.log`
- Console output to stdout
- Format: `%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s() - %(message)s`

**Levels:**
- Configurable via `LOG_LEVEL` environment variable (default: INFO)
- Supports: DEBUG, INFO, WARNING, ERROR, CRITICAL

---

*Stack analysis: 2026-03-27*
