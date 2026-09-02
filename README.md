# 🌐 Segments Manager

![License](https://img.shields.io/badge/license-MIT-blue.svg)

A modern, containerized VLAN segment management system built with **FastAPI** and a **MongoDB** backend. Features a responsive web UI with dark mode, a RESTful API, comprehensive validation, health monitoring, and deployment options for Podman and Kubernetes/OpenShift.

Segments Manager is **decentralized and per-site**: VLAN IDs and EPG names are unique per site, enforced by a MongoDB unique index. There is no VRF and no external IPAM dependency.

---

## ✨ Features

- **Multi-site VLAN management** — manage segments across sites (site1, site2, …)
- **Automatic allocation** — atomically find and allocate an available segment for a cluster
  (one segment belongs to at most one cluster; one cluster may hold several segments)
- **Comprehensive validation** — site IP-prefix enforcement, CIDR/subnet rules, overlap detection, per-site VLAN & EPG uniqueness
- **MongoDB backend** — async (Motor) with atomic allocation and a short in-memory cache
- **CSV/Excel export** and real-time search
- **Responsive web UI** with light/dark themes
- **Pending firewall-request visibility** — while the segment-connectivity orchestrator waits
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
# Edit .env: MONGODB_URL, SITE_NETWORKS

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
  --set-json siteNetworks='{"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}}'
```

In the cluster you do not set `siteNetworks` per service: it is defined once in
`redbull-platform` (`gitops/values/<env>.yaml`) and merged into every chart that
needs it, so segments-manager and segment-connectivity cannot disagree about the
site list. The `--set-json` form above is for standalone installs.

Use `--set mongodb.existingSecret=<name>` to source `MONGODB_URL` from an existing Secret instead.

---

## ⚙️ Configuration

### Environment Variables

```bash
# MongoDB (Required)
MONGODB_URL=mongodb://localhost:27017        # or mongodb+srv://... for Atlas
MONGODB_DB_NAME=segments_manager                 # optional (default: segments_manager)

# Sites (Required) — the single source of truth for configured sites. JSON
# keyed by site name; the list of sites is derived from its keys.
#   pool  the CIDR every segment at that site must fall INSIDE
#   bmc   the site's out-of-band management network. Optional, never read
#         per-request; used only at startup to verify no pool collides with it.
SITE_NETWORKS={"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}, "site2": {"pool": "193.51.0.0/16", "bmc": "10.51.0.0/16"}, "site3": {"pool": "194.52.0.0/16", "bmc": "10.52.0.0/16"}}

# Server (Optional)
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
LOG_LEVEL=INFO

# Auth
API_TOKEN=change-me-to-a-long-random-secret   # REQUIRED — the only credential for write requests
```

**Fail-fast validation**: the app crashes at startup if `MONGODB_URL` or `API_TOKEN` is unset, or if `SITE_NETWORKS` is missing, malformed, has a site without a `pool`, or defines pools that overlap each other or a BMC network. It also refuses to start if the superseded `SITE_PREFIXES` is set while `SITE_NETWORKS` is not — that combination means new code against a stale config.

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
| PUT  | `/api/segments/segment-connectivity-requests` | Set the pending connectivity request ids shown in the UI (empty list clears) *(auth)* |
| DELETE | `/api/segments?segment=` | Delete a segment by CIDR *(auth)* |
| POST | `/api/segments/bulk` | Bulk create *(auth)* |
| POST | `/api/segments/allocate` | Allocate a segment of a given `type` for a cluster at a site *(auth)* |
| POST | `/api/segments/release` | Release a segment by CIDR (Allocated → Available; 409 if Locked) *(auth)* |
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

# Allocate for a cluster (type is required)
curl -X POST http://localhost:8000/api/segments/allocate \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cluster_name":"web-cluster","site":"site1","type":"HC"}'

# Release it again — keyed by the segment CIDR, exactly like unlock
curl -X POST http://localhost:8000/api/segments/release \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"segment":"192.168.1.0/24"}'
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
  "allocated_at": null
}
```

Indexes: unique `{site, vlan_id}`, unique `{segment}`, `{cluster_name}`, `{site}`.

---

## 📄 License

MIT
