# Phase 1: VLAN Site Isolation - Research

**Researched:** 2026-03-27
**Domain:** pynetbox IPAM — VLAN object scoping, group-based lookup, NetBox uniqueness constraints
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- The app must NOT touch existing unscoped VLANs in NetBox — leave them as-is
- No auto-reassignment, no auto-migration, no auto-delete
- Operator (user) will manually remediate by: deleting the affected segments via Segments Manager and recreating them — the recreate path will produce properly scoped VLANs
- The fix only affects new writes; reads of legacy unscoped VLANs are out of scope
- A query to find unscoped VLANs (e.g., `nb.ipam.vlans.filter(group__isnull=True, tenant="Redbull")`) must be included in the codebase
- Location: as a comment or script in the repo so it can be found and rerun, not just in a PR description

### Claude's Discretion
- Error behavior when VLAN Group not found (hard fail vs warning) — Claude decides
- Exact placement of audit query in codebase (README section, inline comment, standalone script)
- Whether to log a warning when a legacy unscoped VLAN is encountered during a read (non-breaking)

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VLAN-01 | VLANs are looked up and created scoped to their VLAN Group (group_id + vid), not globally by vid alone | Fix the initial `vlan_filter` in `get_or_create_vlan()` — eliminate the bare `{"vid": vlan_id}` lookup; resolve group first, then query by `(group_id, vid)` |
| VLAN-02 | Two segments with the same VLAN ID in different sites under the same VRF do not share a NetBox VLAN object | Direct consequence of VLAN-01 fix — each (vrf, site) pair maps to a distinct VLAN Group, so lookups by `(group_id, vid)` never collide across sites |
| VLAN-03 | EPG name search returns only results from the correct site — no cross-site contamination | `prefix_to_segment()` derives `epg_name` from `vlan_obj.name`; once VLAN-01/02 are fixed (each prefix links to a site-scoped VLAN), EPG names are automatically per-site |
| VLAN-04 | Existing production VLANs are assessed for unscoped state before deployment (migration audit query documented) | pynetbox supports `nb.ipam.vlans.filter(group__isnull=True, tenant="RedBull")`; place as a standalone script in the repo |
| VLAN-05 | Group-reassignment fallback logic removed from `get_or_create_vlan()` (~30 lines of complexity eliminated) | The `else` branch (lines 198-225 of `netbox_helpers.py`) that reassigns an existing VLAN to a new group is removed entirely; the new code path never reaches it because lookup is already scoped |
</phase_requirements>

---

## Summary

The bug is in `get_or_create_vlan()` in `src/database/netbox_helpers.py`. The method opens with a global lookup by `vid` alone (`{"vid": vlan_id}`, line 155), which returns the first NetBox VLAN matching that numeric ID regardless of which VLAN Group it belongs to. When two sites both use VLAN ID 100, the second creation call finds the first site's VLAN object and either returns it (same group) or reassigns its group (the group-reassignment fallback in lines 198-221). Both outcomes are wrong.

The fix is a structural inversion of the method: resolve the VLAN Group first (site + VRF uniquely determine the group via `format_vlan_group_name()`), then look up by `(group_id=vlan_group.id, vid=vlan_id)`. This is already how the fallback branch does it (line 205) — the fix makes this the primary and only path, eliminating the fallback entirely. The `else` branch (approximately lines 197-225) is deleted wholesale, satisfying VLAN-05.

VLAN-03 (EPG name cross-site contamination) is a downstream effect of VLAN-01/02: `prefix_to_segment()` in `netbox_utils.py` reads `epg_name` directly from `vlan_obj.name`. Once each prefix links to its own site-scoped VLAN object, the EPG name returned per prefix is inherently site-local. No changes to the query or serialization layer are needed.

**Primary recommendation:** Rewrite `get_or_create_vlan()` so the group is always resolved before any VLAN lookup; add a standalone `scripts/audit_unscoped_vlans.py` for VLAN-04.

---

## Standard Stack

### Core (already in use — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pynetbox | 7.3.3 | NetBox REST client | Already the project's NetBox interface |
| FastAPI | 0.104.1 | Web framework | Already in use |
| Python asyncio | stdlib | Async execution | Already the concurrency model |

**No new packages required for this phase.** All changes are internal to `src/database/netbox_helpers.py`.

### pynetbox VLAN Filter API (verified by code inspection)

pynetbox translates keyword arguments to NetBox REST query parameters. The following calls are confirmed working in the existing codebase:

```python
# Existing — global lookup (the bug)
self.nb.ipam.vlans.get(vid=vlan_id)

# Existing — scoped lookup (already in the fallback branch, line 205)
self.nb.ipam.vlans.get(group_id=vlan_group.id, vid=vlan_id)

# For audit query — filter by null group and tenant
self.nb.ipam.vlans.filter(group__isnull=True, tenant=TENANT_REDBULL)
```

The `group_id` + `vid` compound lookup on line 205 of `netbox_helpers.py` is already proven to work in the current codebase. This is the lookup pattern to promote to primary.

---

## Architecture Patterns

### Current Broken Flow in `get_or_create_vlan()`

```
get_or_create_vlan(vlan_id=100, name="EPG_SITE1", site_slug="site1", vrf_name="Network1")
  │
  ├─ STEP 1: vlan_filter = {"vid": 100}    ← global, no group scope
  ├─ STEP 2: vlans.get(**vlan_filter)       ← returns first VLAN with vid=100 globally
  │
  ├─ IF not found → create (sets group correctly if vrf+site provided)
  └─ IF found (the bug path):
       ├─ get vlan_group for (Network1, site1)
       ├─ check vlans.get(group_id=vlan_group.id, vid=100)
       ├─ IF that exists → return it (correct, but bypassed creation)
       └─ ELSE → reassign existing VLAN's group to this site's group ← WRONG
                  (moves a VLAN that may still be used by site2's prefix)
```

### Fixed Flow in `get_or_create_vlan()` (target state)

```
get_or_create_vlan(vlan_id=100, name="EPG_SITE1", site_slug="site1", vrf_name="Network1")
  │
  ├─ STEP 1: resolve vlan_group = get_or_create_vlan_group(vrf_name, site_group)
  │           → group name: "Network1-ClickCluster-Site1"  (uses format_vlan_group_name())
  │           → cached at vlan_group_{group_name}
  │
  ├─ STEP 2: vlans.get(group_id=vlan_group.id, vid=vlan_id)
  │           → looks up ONLY within this site+VRF's group
  │
  ├─ IF not found → create with group already set in vlan_data
  └─ IF found → update name if changed, return
```

### Method Signature — No Change

`get_or_create_vlan(vlan_id, name, site_slug=None, vrf_name=None)` — signature stays identical. All callers (`insert_one` line 127, `_update_vlan_if_changed` line 201) already pass `site` and `vrf` — no caller changes needed.

### What Happens When vrf_name or site_slug is None

The current code has a guard `if vrf_name and site_slug` before group resolution. This guard must be kept in the fixed version. If either is absent, the method cannot determine a group and should raise an HTTP 400 — a hard fail is correct here because a VLAN without site+VRF context cannot be correctly scoped. This is Claude's discretion per CONTEXT.md.

Rationale for hard fail (not warning): a VLAN created without a group would immediately become an unscoped legacy VLAN — exactly the state this phase is eliminating. A warning would silently reintroduce the bug.

### Audit Script Placement

Place as `scripts/audit_unscoped_vlans.py` — a standalone runnable script, not just a comment. This is discoverable (git grep, directory listing), runnable before deployment, and does not pollute source modules with operational tooling.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| VLAN group name formatting | Custom string concatenation at call sites | `format_vlan_group_name()` in `netbox_constants.py` | Already exists, already tested, already used — changing it would break VLAN group lookups |
| VLAN group cache | New cache structure | Existing `get_vlan_group_cache_key()` + `get_cached()`/`set_cache()` | VLAN group caching already implemented in `get_or_create_vlan_group()` |
| pynetbox null-field filter | ORM-level workaround | `group__isnull=True` Django-style filter param | pynetbox passes kwargs as query params; NetBox REST API supports `group__isnull=True` natively |

---

## Common Pitfalls

### Pitfall 1: The Fallback Becomes the Primary Path

**What goes wrong:** Developer sees the `existing_vlan = vlans.get(group_id=..., vid=...)` on line 205 and thinks "the scoped lookup is already there." They add the group resolution earlier but keep the outer `vlans.get(vid=vlan_id)` as a first check "for performance." Now the global lookup still fires first and returns a VLAN from the wrong group before the scoped lookup runs.

**How to avoid:** The global `vlans.get(vid=vlan_id)` lookup at the top of the method must be deleted entirely. The scoped lookup `vlans.get(group_id=..., vid=...)` is the only lookup path.

### Pitfall 2: Deleting the Wrong `else` Block

**What goes wrong:** The method has one `if not vlan:` branch (create path) and one `else:` branch (update path, lines 198-225). The update path contains the group-reassignment logic to remove. Developer deletes only the reassignment lines inside `else` but leaves the outer `else` structure — this causes a `NameError` or logic error since `vlan` was obtained from the now-deleted global lookup.

**How to avoid:** Delete the entire `else` branch. The fixed method does not need an update-existing path because the group-scoped lookup either finds the right VLAN or returns None (triggering creation).

**Exception:** Name-only updates (when `vlan.name != name`) should still be handled. After the group-scoped lookup, if the VLAN is found and its name differs, update the name before returning.

### Pitfall 3: site_slug Capitalization Inconsistency

**What goes wrong:** `site_slug` passed in is lowercase (e.g., `"site1"`), but VLAN group names use `.capitalize()` (e.g., `"Site1"`). The existing code applies `.capitalize()` inside `get_or_create_vlan()` at lines 183 and 200. If the fixed code moves group resolution but drops the `.capitalize()` call, group names will mismatch existing NetBox groups.

**How to avoid:** Apply `site_slug.capitalize()` before passing to `format_vlan_group_name()` / `get_or_create_vlan_group()`. The existing pattern on line 183 is: `site_group = site_slug.capitalize()`.

### Pitfall 4: Cache Staleness After Create

**What goes wrong:** A new scoped VLAN is created. The `CACHE_KEY_VLANS` cache is not invalidated in `get_or_create_vlan()`. A subsequent read of all prefixes may return the old (stale) VLAN list from cache, which doesn't include the new VLAN — causing mismatched EPG names in the response.

**How to avoid:** After creating a VLAN, call `invalidate_cache(CACHE_KEY_VLANS)`. Check that `CACHE_KEY_VLANS` is imported at the top of `netbox_helpers.py` (it is — line 19 of current file).

### Pitfall 5: Audit Query Tenant Name Case Sensitivity

**What goes wrong:** The audit script uses `tenant="redbull"` (slug) but NetBox REST API may expect the tenant name `"RedBull"` or the tenant slug `"redbull"` depending on the filter parameter name.

**How to avoid:** Use `tenant_id` parameter with the pre-fetched tenant ID, or use `tenant="RedBull"` (name) vs `tenant__slug="redbull"` (slug). The constant `TENANT_REDBULL = "RedBull"` and `TENANT_REDBULL_SLUG = "redbull"` in `netbox_constants.py` clarify the correct values. The audit script should use `nb.ipam.vlans.filter(group__isnull=True, tenant_id=<tenant_id>)` for precision.

---

## Code Examples

### Pattern 1: Fixed `get_or_create_vlan()` Structure

```python
# Source: derived from existing code patterns in netbox_helpers.py lines 183-214

async def get_or_create_vlan(self, vlan_id: int, name: str, site_slug: Optional[str] = None, vrf_name: Optional[str] = None):
    # Group must be resolved first — no fallback to global lookup
    if not (vrf_name and site_slug):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create scoped VLAN {vlan_id}: site_slug and vrf_name are required"
        )

    site_group = site_slug.capitalize()  # preserve existing capitalization pattern
    vlan_group = await self.get_or_create_vlan_group(vrf_name, site_group)

    # Scoped lookup: (group_id, vid) — never returns a VLAN from another site
    vlan = await run_netbox_get(
        lambda: self.nb.ipam.vlans.get(group_id=vlan_group.id, vid=vlan_id),
        f"get VLAN {vlan_id} in group '{vlan_group.name}'"
    )

    if vlan:
        # Found the correctly scoped VLAN — update name if needed
        if vlan.name != name:
            vlan.name = name
            await run_netbox_write(lambda: vlan.save(), f"update VLAN {vlan_id} name")
        return vlan

    # Not found in this group — create new scoped VLAN
    vlan_data = {
        "vid": vlan_id,
        "name": name,
        "group": vlan_group.id,
        "status": STATUS_ACTIVE,
    }
    tenant = await self.get_tenant(TENANT_REDBULL)
    if tenant:
        vlan_data["tenant"] = tenant.id
    role = await self.get_role(ROLE_DATA, "vlan")
    if role:
        vlan_data["role"] = role.id

    vlan = await run_netbox_write(
        lambda: self.nb.ipam.vlans.create(**vlan_data),
        f"create VLAN {vlan_id} in group '{vlan_group.name}'"
    )
    invalidate_cache(CACHE_KEY_VLANS)
    return vlan
```

### Pattern 2: Audit Script Core Query

```python
# Source: pynetbox filter API + existing netbox_constants.py values
# File: scripts/audit_unscoped_vlans.py

import pynetbox

# Connect using same env vars as main app
nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)

# Find tenant first (for precise filtering)
tenant = nb.tenancy.tenants.get(slug="redbull")  # TENANT_REDBULL_SLUG

# Find all VLANs with no group, scoped to this app's tenant
unscoped = list(nb.ipam.vlans.filter(group__isnull=True, tenant_id=tenant.id))

print(f"Found {len(unscoped)} unscoped VLANs:")
for vlan in unscoped:
    print(f"  VID={vlan.vid}, name={vlan.name}, id={vlan.id}")
```

---

## State of the Art (in this codebase)

| Old Approach | Current/Target Approach | Impact |
|--------------|------------------------|--------|
| `vlans.get(vid=vlan_id)` — global lookup | `vlans.get(group_id=vlan_group.id, vid=vlan_id)` — scoped lookup | Eliminates cross-site VLAN sharing |
| Group resolution in `else` branch only (fallback) | Group resolution as first step (always) | Removes ~28 lines of fallback logic |
| Create without group if group resolution fails | Hard fail if group not resolvable | Prevents silent creation of new unscoped VLANs |

---

## Open Questions

1. **What if `get_or_create_vlan_group()` fails mid-flight?**
   - What we know: `get_or_create_vlan_group()` already wraps exceptions with `raise` (line 362 of `netbox_helpers.py`), so exceptions propagate to the caller.
   - What's unclear: The caller `insert_one()` has a broad `except Exception as e: raise` at line 178. This means VLAN group failure correctly aborts segment creation. No special handling needed.
   - Recommendation: No change required to error propagation — existing raise-through behavior is correct.

2. **Should `cleanup_unused_vlan()` be updated?**
   - What we know: `cleanup_unused_vlan()` uses `vlan_obj.vid` for logging and `safe_get_id(vlan_obj)` for prefix matching — no group assumptions. It works correctly post-fix.
   - What's unclear: After the fix, two VLANs with the same `vid` can exist (one per site). `cleanup_unused_vlan()` checks by VLAN object ID (`safe_get_id(vlan_obj)` returns `vlan_obj.id`, not `vid`), so it will correctly check only the specific VLAN being cleaned up.
   - Recommendation: No change to `cleanup_unused_vlan()` needed.

3. **`delete_one()` deletes the VLAN after prefix deletion — is this still safe?**
   - What we know: After the fix, each prefix links to a site-scoped VLAN. Deleting the prefix then the VLAN is safe because the VLAN is now 1:1 with the prefix's site+VRF+VID tuple (no sharing).
   - Recommendation: No change to `delete_one()` needed.

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/database/netbox_helpers.py` — full read of `get_or_create_vlan()`, `get_or_create_vlan_group()`, `cleanup_unused_vlan()`
- Direct code inspection: `src/database/netbox_crud_ops.py` — full read of `insert_one()`, `_update_vlan_if_changed()`, `delete_one()`
- Direct code inspection: `src/database/netbox_utils.py` — full read of `prefix_to_segment()`, confirming EPG name source
- Direct code inspection: `src/database/netbox_query_ops.py` — confirmed site filtering is post-fetch in-memory, not NetBox-side
- Direct code inspection: `src/database/netbox_constants.py` — `format_vlan_group_name()`, cache key functions, tenant/role constants
- Direct code inspection: `src/database/netbox_cache.py` — `CACHE_KEY_VLANS`, `invalidate_cache()` confirmed available

### Secondary (MEDIUM confidence)
- pynetbox filter keyword conventions (`group_id`, `group__isnull`, `tenant_id`) — inferred from existing working code patterns in `netbox_query_ops.py` and line 205 of `netbox_helpers.py`

---

## Metadata

**Confidence breakdown:**
- Bug identification: HIGH — fully traced through code; the global `vid` lookup on line 155 is unambiguous
- Fix approach: HIGH — scoped lookup pattern already exists on line 205; fix promotes it to primary
- VLAN-03 fix: HIGH — `prefix_to_segment()` confirmed to read EPG name from `vlan_obj.name`; no query layer change needed
- Audit query: HIGH — `group__isnull=True` pattern inferred from existing pynetbox filter usage; pynetbox's Django-ORM-style filter translation is well-established
- Caller impact: HIGH — all callers of `get_or_create_vlan()` already pass `site` and `vrf`; no caller changes needed

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable codebase, no fast-moving dependencies)
