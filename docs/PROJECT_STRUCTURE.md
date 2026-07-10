# Project Structure

This document describes the organization of the Segments Manager project directory.

## Directory Layout

```
segments_2/
├── main.py                    # Entry point - starts the application
├── README.md                  # User-facing documentation
├── CLAUDE.md                  # Development guidelines for AI assistants
├── requirements.txt           # Python dependencies
├── run.sh                     # Podman deployment script
├── Dockerfile                 # Container image definition
│
├── src/                       # Application source code
│   ├── run.py                # Server startup (uvicorn)
│   ├── app.py                # FastAPI application setup
│   ├── api/                  # REST API endpoints
│   ├── config/               # Configuration and settings
│   ├── database/             # NetBox storage integration (9 modules)
│   ├── models/               # Pydantic data models
│   ├── services/             # Business logic layer
│   └── utils/                # Utility functions and validators
│
├── static/                    # Web UI assets (served by FastAPI)
│   ├── html/                 # HTML pages
│   ├── css/                  # Stylesheets
│   └── js/                   # JavaScript
│
├── tests/                     # Test suite
│   ├── test_api.py           # Main integration tests (72 tests, 66.7% passing)
│   ├── test_api_quick.py     # Quick validation suite (10 tests, 90% passing)
│   ├── test_comprehensive.py # Comprehensive validation (80+ tests)
│   ├── test_vlan_allocation.py
│   ├── test_netbox_connection.py
│   ├── test_api_integration.py
│   ├── README_TESTING.md     # Testing guide
│   └── TEST_STATUS.md        # Test suite status report
│
├── docs/                      # Technical documentation
│   ├── PROJECT_STRUCTURE.md  # This file
│   ├── CODE_ANALYSIS_REPORT.md
│   ├── DATABASE_ARCHITECTURE_ANALYSIS.md
│   ├── ISSUES_FOUND_AND_FIXED.md
│   ├── REDIS_CACHE_DESIGN.md
│   └── TEST_SUITE_RESULTS.md
│
├── sample_data/               # Example data files
│   ├── bulk_segments.csv
│   └── bulk_segments_selected.csv
│
├── scripts/                   # Utility scripts
│   ├── create_netbox_resources.py
│   └── allocate-vlan-ci.sh
│
├── deploy/                    # Deployment configurations
│   ├── helm/                 # Kubernetes Helm chart
│   └── scripts/              # Deployment scripts
│
└── test-data/                 # Test data fixtures
    └── segments.json
```

## Key Files

### Entry Points
- **main.py** - Application entry point, delegates to `src/run.py`
- **run.sh** - Podman deployment script (build, start, stop, logs, etc.)

### Configuration
- **.env** - Environment variables (not in git, copy from .env.example)
- **requirements.txt** - Python dependencies (8 packages)
- **CLAUDE.md** - Development guidelines and architecture documentation

### Documentation
- **README.md** - User documentation (how to run, configure, use)
- **docs/** - Technical architecture, analysis, and design documents
- **tests/README_TESTING.md** - Testing guide and API behavior reference

### Source Code
- **src/api/routes.py** - All API endpoints
- **src/database/** - NetBox integration (1,560 lines across 9 modules)
- **src/services/** - Business logic (allocation, segments, stats, export)
- **src/utils/validators.py** - Comprehensive validation (~700 lines)

### Testing
- **tests/test_api.py** - Main integration test suite (72 tests)
- **tests/test_api_quick.py** - Quick validation (10 tests, fast)
- **tests/TEST_STATUS.md** - Current test results and improvement tracking

## File Organization Rules

### What Goes Where

**Base Directory** (`/`)
- Only essential files: main.py, README.md, CLAUDE.md, config files
- No test scripts, no markdown documentation (except README/CLAUDE)

**docs/** - Technical Documentation
- Architecture analysis and design documents
- Code analysis reports
- Technical debt and improvement tracking
- **NOT** user-facing documentation (that's README.md)

**tests/** - All Test Files
- Test scripts (test_*.py)
- Test documentation (README_TESTING.md, TEST_STATUS.md)
- Test backups and fixtures

**sample_data/** - Example Data
- CSV files with sample segments
- Example bulk import data
- Reference datasets

**scripts/** - Utility Scripts
- NetBox setup scripts
- CI/CD helper scripts
- Development utilities
- **NOT** application code

**src/** - Application Source
- All production Python code
- Organized by layer: api, services, database, models, utils

**static/** - Web UI Assets
- HTML, CSS, JavaScript for the web interface
- Served by FastAPI at runtime

**deploy/** - Deployment Configs
- Kubernetes/Helm charts
- Container orchestration
- Deployment automation

## Recent Changes (2025-12-08)

### Files Moved
```bash
# Moved to docs/
CODE_ANALYSIS_REPORT.md → docs/
DATABASE_ARCHITECTURE_ANALYSIS.md → docs/
ISSUES_FOUND_AND_FIXED.md → docs/
REDIS_CACHE_DESIGN.md → docs/
TEST_SUITE_RESULTS.md → docs/

# Moved to sample_data/
bulk_segments.csv → sample_data/
bulk_segments_selected.csv → sample_data/

# Moved to tests/
test_api_integration.py → tests/
test_comprehensive.py → tests/
test_netbox_connection.py → tests/
test_vlan_allocation.py → tests/

# Moved to scripts/
create_netbox_resources.py → scripts/
```

### New Folders Created
- **docs/** - Consolidated technical documentation
- **sample_data/** - Sample CSV files for bulk imports

## Development Workflow

### Running Tests
```bash
# Quick validation (90% pass rate, fast)
pytest tests/test_api_quick.py -v

# Full integration suite (66.7% pass rate, comprehensive)
pytest tests/test_api.py -v

# Comprehensive validation (80+ edge case tests)
python tests/test_comprehensive.py
```

### Deployment
```bash
# Build and deploy with Podman
./run.sh deploy

# Or individual steps
./run.sh build   # Build container image
./run.sh start   # Start container
./run.sh logs    # View logs
./run.sh test    # Run tests
```

### Documentation
- **For users**: Update [README.md](../README.md)
- **For developers**: Update [CLAUDE.md](../CLAUDE.md)
- **For architecture**: Add to [docs/](.)
- **For tests**: Update [tests/README_TESTING.md](../tests/README_TESTING.md)

## Notes

- Virtual environment (`.venv/`) is at project root (not committed to git)
- Log file (`segments_manager.log`) is at project root (not committed to git)
- Git ignores: `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `logs/`, `*.log`

---

**Last Updated**: 2025-12-08
**Project Version**: v3.2.0
