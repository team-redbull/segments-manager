# Segments Manager

## What This Is

Segments Manager is a production-grade network VLAN allocation and management system that provides an intelligent API layer on top of NetBox IPAM. It manages VLAN segments across multiple sites and VRFs, where each VRF+Site combination has its own IP prefix space. The system automates VLAN segment allocation, enforces uniqueness constraints per VRF+Site scope, and exposes a FastAPI REST API with a web UI.

## Core Value

Operators can create, allocate, and search VLANs and prefixes across any VRF+Site combination without polluting each other's data in NetBox.

## Requirements

### Validated

- ✓ Segment CRUD (create, read, update, delete) per VRF+Site — existing
- ✓ VLAN allocation across sites (auto-assign available segment to a cluster) — existing
- ✓ Multi-VRF support — each VRF has independent prefix space per site — existing
- ✓ Site IP prefix enforcement (e.g. site1 in VRF1 = 192.x.x.x) — existing
- ✓ NetBox as source of truth (all reads/writes via pynetbox) — existing
- ✓ TTL-based caching with in-flight deduplication — existing
- ✓ Web UI with search, filter, dark/light theme — existing
- ✓ CSV/Excel export — existing
- ✓ File-based session authentication — existing
- ✓ Containerized deployment (Podman/Docker) — existing

### Active

- [ ] Fix VLAN collision bug — same VLAN ID in different sites under the same VRF shares one NetBox VLAN object, causing both prefixes to appear under the same VLAN and EPG name searches to return results from wrong sites
- [ ] Expand EPG name validation to accept CIDR format (dots + forward slashes, e.g. `192.168.1.0/24`)
- [ ] Remove XSS injection validation from EPG name and description fields
- [ ] Remove over-zealous validators that reject data NetBox itself accepts — trust NetBox's own validation for non-critical fields

### Out of Scope

- Real-time notifications / webhooks — not needed
- Multi-tenant auth / RBAC — single-operator tool
- Mobile UI — web-first
- Sync back from NetBox UI changes — out of scope for now

## Context

This is a brownfield project. The codebase is at v3.2.0 with a clean architecture (API → Service → Database layers). The core bug is in VLAN scoping: when creating a VLAN object in NetBox, the code is not properly scoping it to a VLAN Group (which is site-specific). Two sites with the same VLAN ID end up sharing the same NetBox VLAN object, so their prefixes become entangled.

The validation layer (`src/utils/validators.py`, ~700+ lines) has grown overly strict. The user wants to reduce friction by:
1. Allowing CIDR-format EPG names (common when EPG = segment address)
2. Removing XSS checks (not relevant for internal network management tool)
3. Removing checks that duplicate what NetBox already enforces

## Constraints

- **Tech Stack**: Python 3.11, FastAPI, pynetbox — no stack changes
- **NetBox**: Read-only tokens supported — no DCIM write permissions assumed
- **Backward compat**: Existing NetBox data must remain intact (fixes must not corrupt existing prefixes/VLANs)
- **Site Groups**: App does NOT create site groups — GET only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| VLAN must be scoped to VLAN Group (site-specific) | Root cause of collision bug — VLANs without site scope conflict across sites | — Pending |
| Remove XSS validation | Internal tool, operators are trusted, XSS checks block valid CIDR inputs | — Pending |
| Trust NetBox for non-critical field validation | Reduces maintenance burden, single source of truth | — Pending |

---
*Last updated: 2026-03-27 after initialization*
