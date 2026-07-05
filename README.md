# 🌐 VLAN Segment Manager

![License](https://img.shields.io/badge/license-MIT-blue.svg)

A modern, containerized VLAN segment management system built with **FastAPI** and a **MongoDB** backend. Features a responsive web UI with dark mode, a RESTful API, comprehensive validation, health monitoring, and deployment options for Podman and Kubernetes/OpenShift.

VLAN Manager is **decentralized and per-site**: VLAN IDs and EPG names are unique per site, enforced by a MongoDB unique index. There is no VRF and no external IPAM dependency.

---

## ✨ Features

- **Multi-site VLAN management** — manage segments across sites (site1, site2, …)
- **Automatic allocation** — atomically find and allocate an available segment for a cluster
- **Shared segments** — multiple clusters can share one VLAN (comma-separated)
- **Comprehensive validation** — site IP-prefix enforcement, CIDR/subnet rules, overlap detection, per-site VLAN & EPG uniqueness
- **MongoDB backend** — async (Motor) with atomic allocation and a short in-memory cache
- **CSV/Excel export** and real-time search
- **Responsive web UI** with light/dark themes
- **Health monitoring** — `/api/health` pings MongoDB

---

## 🏗️ Architecture

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

Clean architecture: **API** (`src/api`) → **Services** (`src/services`) → **DatabaseUtils** (`src/utils/database`) → **Mongo layer** (`src/database`), with **Pydantic models** and layered **validators**.

---

## 🚀 Quick Start

### Option 1: Direct Python

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: MONGODB_URL, SITES, SITE_PREFIXES

# Run
python main.py           # http://localhost:8000
```

### Option 2: Container (Podman)

```bash
# Build + run
./run.sh deploy

# Or manually
podman build -t vlan-manager:latest .
podman run -d --name vlan-manager -p 8000:8000 --env-file .env vlan-manager:latest
```

### Option 3: Kubernetes / OpenShift (Helm)

```bash
helm install vlan-manager deploy/helm \
  --set mongodb.url="mongodb+srv://user:pass@cluster/..." \
  --set config.sites="site1,site2,site3" \
  --set config.sitePrefixes="site1:192,site2:193,site3:194"
```

Use `--set mongodb.existingSecret=<name>` to source `MONGODB_URL` from an existing Secret instead.

---

## ⚙️ Configuration

### Environment Variables

```bash
# MongoDB (Required)
MONGODB_URL=mongodb://localhost:27017        # or mongodb+srv://... for Atlas
MONGODB_DB_NAME=vlan_manager                 # optional (default: vlan_manager)

# Sites (Required)
SITES=site1,site2,site3

# Site IP Prefix Validation (Required) — every site MUST have an entry
SITE_PREFIXES=site1:192,site2:193,site3:194

# Server (Optional)
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# Auth (Optional; default admin/admin)
AUTH_USERNAME=admin
AUTH_PASSWORD=admin
```

**Fail-fast validation**: the app crashes at startup if `MONGODB_URL` is unset or if any site in `SITES` lacks a `SITE_PREFIXES` entry.

---

## 📊 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/segments` | List segments (filter by `site`, `allocated`) |
| GET  | `/api/segments/search?q=` | Search by cluster, EPG, VLAN, description, segment |
| POST | `/api/segments` | Create a segment *(auth)* |
| GET  | `/api/segments/{id}` | Get one segment |
| PUT  | `/api/segments/{id}` | Update a segment *(auth)* |
| PUT  | `/api/segments/{id}/clusters` | Update cluster assignment *(auth)* |
| DELETE | `/api/segments/{id}` | Delete a segment *(auth)* |
| POST | `/api/segments/bulk` | Bulk create *(auth)* |
| POST | `/api/allocate-vlan` | Allocate a VLAN for a cluster *(auth)* |
| POST | `/api/release-vlan` | Release a cluster's allocation *(auth)* |
| GET  | `/api/sites` | Configured sites |
| GET  | `/api/stats` | Per-site statistics |
| GET  | `/api/health` | Health check (MongoDB connectivity) |
| GET  | `/api/export/segments/{csv,excel}` | Export segments |

Auth is HTTP Basic (or session cookie via `/api/auth/login`). Example:

```bash
# Create a segment
curl -u admin:admin -X POST http://localhost:8000/api/segments \
  -H "Content-Type: application/json" \
  -d '{"site":"site1","vlan_id":100,"epg_name":"EPG_PROD_01","segment":"192.168.1.0/24","dhcp":false}'

# Allocate for a cluster
curl -u admin:admin -X POST http://localhost:8000/api/allocate-vlan \
  -H "Content-Type: application/json" \
  -d '{"cluster_name":"web-cluster","site":"site1"}'
```

---

## 🧪 Testing

```bash
pytest tests/test_api.py -v      # integration tests (server must be running)
python test_comprehensive.py     # comprehensive validation tests
```

---

## 📦 Data Model

Collection `segments`:

```json
{
  "site": "site1",
  "vlan_id": 100,
  "epg_name": "EPG_PROD_01",
  "segment": "192.168.1.0/24",
  "dhcp": false,
  "description": "",
  "cluster_name": null,
  "allocated_at": null,
  "released": false,
  "released_at": null
}
```

Indexes: unique `{site, vlan_id}`, unique `{segment}`, `{cluster_name}`, `{site}`.

---

## 📄 License

MIT
