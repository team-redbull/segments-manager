# 🌐 Segments Manager

![License](https://img.shields.io/badge/license-MIT-blue.svg)

A modern, containerized VLAN segment management system built with **FastAPI** and a **MongoDB** backend. Features a responsive web UI with dark mode, a RESTful API, comprehensive validation, health monitoring, and deployment options for Podman and Kubernetes/OpenShift.

Segments Manager is **decentralized and per-site**: VLAN IDs and EPG names are unique per site, enforced by a MongoDB unique index. There is no VRF and no external IPAM dependency.

---

## ✨ Features

- **Multi-site VLAN management** — manage segments across sites (site1, site2, …)
- **Automatic allocation** — atomically find and allocate an available segment for a cluster
- **Shared segments** — multiple clusters can share one VLAN (comma-separated)
- **Comprehensive validation** — site IP-prefix enforcement, CIDR/subnet rules, overlap detection, per-site VLAN & EPG uniqueness
- **MongoDB backend** — async (Motor) with atomic allocation and a short in-memory cache
- **CSV/Excel export** and real-time search
- **Responsive web UI** with light/dark themes
- **Pending firewall-request visibility** — while the connectivity orchestrator waits
  for firewall approval, a **Requests ID** button next to the segment's status opens
  a popover with the pending request ids (cleared automatically on completion)
- **Health monitoring** — `/api/health` pings MongoDB

---

## 🏗️ Architecture

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

Clean architecture: **API** (`src/api`) → **Services** (`src/services`) → **DatabaseUtils** (`src/utils/database`) → **Mongo layer** (`src/database`), with **Pydantic models** and layered **validators**.

---

## 🚀 Quick Start

### Option 1: Direct Python

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: MONGODB_URL, SITE_PREFIXES

# Run
python main.py           # http://localhost:8000
```

### Option 2: Container (Podman)

```bash
# Build + run
./run.sh deploy

# Or manually
podman build -t segments-manager:latest .
podman run -d --name segments-manager -p 8000:8000 --env-file .env segments-manager:latest
```

### Option 3: Kubernetes / OpenShift (Helm)

```bash
helm install segments-manager deploy/helm \
  --set mongodb.url="mongodb+srv://user:pass@cluster/..." \
  --set config.sitePrefixes="site1:192,site2:193,site3:194"
```

Use `--set mongodb.existingSecret=<name>` to source `MONGODB_URL` from an existing Secret instead.

---

## ⚙️ Configuration

### Environment Variables

```bash
# MongoDB (Required)
MONGODB_URL=mongodb://localhost:27017        # or mongodb+srv://... for Atlas
MONGODB_DB_NAME=segments_manager                 # optional (default: segments_manager)

# Sites (Required) — the single source of truth for configured sites,
# formatted as site:first-octet. The list of sites is derived from its keys.
SITE_PREFIXES=site1:192,site2:193,site3:194

# Server (Optional)
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# Auth
API_TOKEN=change-me-to-a-long-random-secret   # REQUIRED — the only credential for write requests
```

**Fail-fast validation**: the app crashes at startup if `MONGODB_URL` or `API_TOKEN` is unset, or if `SITE_PREFIXES` is empty/unset.

---

## 📊 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/segments` | List segments (filter by `site`, `allocated`) |
| GET  | `/api/segments/search?q=` | Search by cluster, EPG, VLAN, segment |
| POST | `/api/segments` | Create a segment *(auth)* |
| GET  | `/api/segments/by-segment?segment=` | Get one segment by CIDR |
| PATCH | `/api/segments` | Update a segment's DHCP flag *(auth)* |
| PUT  | `/api/segments/clusters` | Update cluster assignment *(auth)* |
| POST | `/api/segments/unlock` | Unlock a segment (Locked → Available) *(auth)* |
| PUT  | `/api/segments/connectivity-requests` | Set the pending connectivity request ids shown in the UI (empty list clears) *(auth)* |
| DELETE | `/api/segments?segment=` | Delete a segment by CIDR *(auth)* |
| POST | `/api/segments/bulk` | Bulk create *(auth)* |
| POST | `/api/allocate-segment` | Allocate a segment for a cluster *(auth)* |
| POST | `/api/release-segment` | Release a cluster's allocation *(auth)* |
| GET  | `/api/sites` | Configured sites |
| GET  | `/api/stats` | Per-site statistics |
| GET  | `/api/health` | Health check (MongoDB connectivity) |
| GET  | `/api/export/segments/{csv,excel}` | Export segments |

Single-segment operations are keyed by the segment **CIDR** (the natural key — unique and immutable), never by a database id: reads and deletes take it as a `?segment=` query parameter, writes carry it in the request body.

**Read (`GET`) endpoints are open; every write (`POST`/`PUT`/`PATCH`/`DELETE`) requires the API token** as a `Authorization: Bearer <API_TOKEN>` header. The token is the only credential — there is no username/password login. Example:

```bash
# Create a segment
curl -X POST http://localhost:8000/api/segments \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"site":"site1","vlan_id":100,"epg_name":"EPG_PROD_01","segment":"192.168.1.0/24","dhcp":true}'

# Allocate for a cluster
curl -X POST http://localhost:8000/api/allocate-segment \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cluster_name":"web-cluster","site":"site1"}'
```

---

## 🧪 Testing

Integration tests run against a **live server** (see [`tests/README.md`](tests/README.md)).

```bash
pip install pytest requests

# Against a locally running server (http://127.0.0.1:8000)
pytest tests/ -v

# Against a different target
SEGMENTS_MANAGER_URL=http://host:8000 pytest tests/ -v
```

The suite skips (rather than fails) if the server is unreachable, and cleans up
every segment and allocation it creates. To run against the container image with
a throwaway MongoDB, see [`tests/README.md`](tests/README.md).

---

## 📦 Data Model

Collection `segments`:

```json
{
  "site": "site1",
  "vlan_id": 100,
  "epg_name": "EPG_PROD_01",
  "segment": "192.168.1.0/24",
  "dhcp": true,
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
