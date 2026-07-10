---
phase: 01-vlan-site-isolation
plan: 01
subsystem: database
tags: [netbox, pynetbox, vlan, scoping, ipam, audit]

# Dependency graph
requires: []
provides:
  - "get_or_create_vlan() with group-first scoped (group_id, vid) lookup — no global bare-vid fallback"
  - "HTTP 400 guard preventing silent creation of unscoped VLANs"
  - "scripts/audit_unscoped_vlans.py standalone pre-deployment audit script"
affects:
  - "02-vlan-site-isolation"
  - "segment creation flow (netbox_crud_ops.py calls get_or_create_vlan)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "VLAN scoping: always resolve VLAN Group (site+VRF) first, then lookup by (group_id, vid)"
    - "Hard-fail guard: raise HTTP 400 immediately when required scoping context is absent"
    - "Standalone operator scripts: standalone Python script using pynetbox directly (no app imports)"

key-files:
  created:
    - scripts/audit_unscoped_vlans.py
  modified:
    - src/database/netbox_helpers.py

key-decisions:
  - "Group resolution is step one, not a fallback — eliminates the root cause of the VLAN sharing bug"
  - "No silent unscoped VLAN creation: missing site_slug or vrf_name raises HTTP 400"
  - "Audit script is read-only — does not migrate existing unscoped VLANs (operators must remediate manually via UI/API)"
  - "invalidate_cache(CACHE_KEY_VLANS) called after VLAN creation to keep cache coherent"

patterns-established:
  - "Scoped VLAN lookup: self.nb.ipam.vlans.get(group_id=vlan_group.id, vid=vlan_id)"
  - "Pre-deployment audit pattern: filter(group__isnull=True, tenant_id=...) to find legacy unscoped VLANs"

requirements-completed: [VLAN-01, VLAN-02, VLAN-03, VLAN-04, VLAN-05]

# Metrics
duration: 2min
completed: 2026-03-27
---

# Phase 1 Plan 01: VLAN Site Isolation — Scoped VLAN Lookup Fix Summary

**Eliminated VLAN cross-site data corruption by rewriting get_or_create_vlan() to resolve the VLAN Group first and perform scoped (group_id, vid) lookups exclusively, plus added a standalone pre-deployment audit script.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T16:51:11Z
- **Completed:** 2026-03-27T16:53:12Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Rewrote `get_or_create_vlan()` — group resolution is now step 1, lookup is always `(group_id, vid)`, the ~28-line group-reassignment else-block is fully removed
- Added HTTP 400 hard-fail guard: calling without `site_slug` or `vrf_name` fails immediately (no silent unscoped VLAN creation)
- Created `scripts/audit_unscoped_vlans.py` — standalone, read-only, exits 0 (safe) or 1 (remediation needed), usable as a CI gate before deployment

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite get_or_create_vlan() with group-first scoped lookup** - `f24ea40` (fix)
2. **Task 2: Create audit_unscoped_vlans.py operator script** - `c56fd18` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/database/netbox_helpers.py` - get_or_create_vlan() rewritten: group-first lookup, scoped (group_id, vid) query, HTTP 400 guard, removed else-block, added invalidate_cache import
- `scripts/audit_unscoped_vlans.py` - New standalone pre-deployment audit script: reads NETBOX_URL/NETBOX_TOKEN, queries group__isnull=True scoped to Redbull tenant, prints per-VLAN remediation hints, exits 0/1/2

## Decisions Made
- **Group resolution first:** The old code resolved the group as a fallback after a global vid-only lookup. The new code resolves the group unconditionally as the first operation. This is the minimal change that eliminates the bug.
- **No migration logic in app:** Existing unscoped VLANs are NOT touched by the application — operators must delete and recreate segments via Segments Manager. The audit script identifies what needs remediation.
- **HTTP 400 over silent fallback:** A call without site_slug/vrf_name now raises HTTP 400 immediately rather than creating a VLAN with no group. This makes misconfiguration loud instead of silent.

## Deviations from Plan

None — plan executed exactly as written.

The grep pattern `'vid": vlan_id'` in the plan's verification step produced a false-positive match on line 172 (`"vid": vlan_id` inside `vlan_data` creation payload), but this is correct: that `vid` key is setting the VID on the new VLAN object, not performing a bare-vid lookup. The actual bare-vid lookup variables (`vlan_filter`, `vlans.get(vid=`) are confirmed absent.

## Issues Encountered
None.

## User Setup Required
None — no external service configuration required.

Operators must run `scripts/audit_unscoped_vlans.py` before deploying this fix to identify any unscoped VLANs in production NetBox that need manual remediation.

## Next Phase Readiness
- VLAN scoping bug is fixed — each site+VID combination now gets its own independent NetBox VLAN object
- Pre-deployment audit script is ready for operators to run against production
- Phase 2 can address additional site isolation concerns (search scoping, etc.) once production migration is complete

---
*Phase: 01-vlan-site-isolation*
*Completed: 2026-03-27*
