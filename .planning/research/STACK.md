# Technology Stack: VLAN Scoping Bug Fix

**Project:** Segments Manager - NetBox VLAN Scoping Fix
**Researched:** 2026-03-27
**Overall Confidence:** HIGH (verified against NetBox official docs + pynetbox docs + codebase analysis)

## Problem Analysis

The current code has a critical VLAN collision bug. The root cause is in `netbox_helpers.py` line 155:

```python
vlan_filter = {"vid": vlan_id}
vlan = await run_netbox_get(
    lambda: self.nb.ipam.vlans.get(**vlan_filter),
    f"get VLAN {vlan_id}"
)
```

This looks up VLANs by VID alone -- no group scoping. When Site1 creates VLAN 22 and Site2 also needs VLAN 22, the `.get(vid=22)` call returns the **first** VLAN 22 (Site1's), and the code either reuses it or fails. Two prefixes in different sites end up sharing one VLAN object.

## How NetBox VLAN Scoping Actually Works

**Confidence: HIGH** (NetBox official documentation)

### NetBox Data Model for VLANs

| Concept | NetBox Object | Uniqueness Constraint |
|---------|--------------|----------------------|
| VLAN Group | `ipam.vlan_groups` | Scopes VLAN uniqueness. Each group can be scoped to a Site, SiteGroup, Region, Location, etc. |
| VLAN | `ipam.vlans` | **Unique by (group, vid) AND (group, name)** within a group. VLANs outside any group have NO uniqueness enforcement. |
| Prefix | `ipam.prefixes` | Scoped to SiteGroup via `scope_type`/`scope_id`. Links to a VLAN via `vlan` field. |

### Key Rules

1. **VLAN uniqueness is enforced per VLAN Group** -- two VLANs with `vid=22` CAN coexist if they belong to different VLAN Groups.
2. **VLAN Groups can be scoped to a SiteGroup** -- this is the correct way to make VLANs site-specific. The app already creates VLAN Groups in format `{VRF}-ClickCluster-{Site}` (e.g., `Network1-ClickCluster-Site1`).
3. **Direct VLAN-to-site assignment is deprecated** in NetBox. The official guidance is: use VLAN Groups with scope, not the legacy `site` field on VLANs.
4. **VLANs not in any group have NO uniqueness** -- they can have overlapping VIDs and names freely.

### VLAN Group Scope Fields (REST API)

When creating a VLAN Group scoped to a SiteGroup:

```python
# VLAN Group creation with scope
nb.ipam.vlan_groups.create(
    name="Network1-ClickCluster-Site1",
    slug="network1-clickcluster-site1",
    scope_type="dcim.sitegroup",   # ContentType string
    scope_id=<site_group_id>,       # ID of the SiteGroup object
)
```

**Current gap:** The code in `get_or_create_vlan_group()` (line 345) creates VLAN Groups WITHOUT `scope_type`/`scope_id`. The groups exist but are not scoped to SiteGroups, which means NetBox does not enforce site-level isolation at the group level. This is not the root cause of the collision (that is the missing group filter on VLAN lookup), but it is a correctness gap.

## Recommended Stack (No Changes Needed)

The existing stack is correct. The bug is in API call logic, not technology choices.

### Core (Unchanged)

| Technology | Version | Purpose | Status |
|------------|---------|---------|--------|
| Python | 3.11+ | Runtime | Keep |
| FastAPI | 0.104.1 | Web framework | Keep |
| pynetbox | 7.3.3 | NetBox API client | Keep -- supports all needed VLAN Group operations |
| Pydantic | 2.5.0 | Data validation | Keep |

### pynetbox 7.3.3 -- Relevant API Surface

**Confidence: HIGH** (pynetbox official docs + GitHub)

| Operation | pynetbox Call | Notes |
|-----------|--------------|-------|
| Get VLAN by group + VID | `nb.ipam.vlans.get(group_id=<id>, vid=<vid>)` | **This is the fix.** Must filter by group_id, not just vid. |
| Get VLAN by group slug + VID | `nb.ipam.vlans.get(group="<slug>", vid=<vid>)` | Alternative: filter by group slug string. |
| Filter VLANs in group | `nb.ipam.vlans.filter(group_id=<id>, vid=<vid>)` | Returns list. Use when `.get()` might return multiple. |
| Create VLAN in group | `nb.ipam.vlans.create(vid=<vid>, name="<name>", group=<group_id>, ...)` | Pass `group` as the VLAN Group ID. |
| Get/create VLAN Group | `nb.ipam.vlan_groups.get(name="<name>")` / `.create(...)` | Already implemented. |
| Create VLAN Group with scope | `nb.ipam.vlan_groups.create(name=..., slug=..., scope_type="dcim.sitegroup", scope_id=<id>)` | Enhancement: scope groups to SiteGroups. |
| Available VLANs in group | `vlan_group.available_vlans.list()` / `.create()` | Auto-allocate next available VID. Available since NetBox 3.2+. |

## Specific Fixes Required

### Fix 1: VLAN Lookup Must Include Group (CRITICAL)

**File:** `src/database/netbox_helpers.py`, method `get_or_create_vlan`

**Current (broken):**
```python
vlan_filter = {"vid": vlan_id}
vlan = await run_netbox_get(
    lambda: self.nb.ipam.vlans.get(**vlan_filter),
    f"get VLAN {vlan_id}"
)
```

**Required approach:**
```python
# 1. Resolve the VLAN Group first (already have vrf_name + site_slug)
# 2. Look up VLAN scoped to that group
vlan = nb.ipam.vlans.get(group_id=vlan_group.id, vid=vlan_id)
```

**Why:** Without `group_id`, pynetbox sends `GET /api/ipam/vlans/?vid=22` which returns the first match across ALL groups. With `group_id`, it sends `GET /api/ipam/vlans/?group_id=X&vid=22` which returns only the VLAN in that specific group.

**Confidence: HIGH**

### Fix 2: VLAN Group Should Be Resolved Before VLAN Lookup

The current `get_or_create_vlan` method has a structural problem: it tries to look up the VLAN first (line 155-160, without group), then only resolves the VLAN Group later (line 181-188, during creation). The logic must be restructured so the VLAN Group is resolved FIRST, then the VLAN is looked up within that group.

**Required call order:**
1. `get_or_create_vlan_group(vrf_name, site_slug)` -- get the group
2. `nb.ipam.vlans.get(group_id=group.id, vid=vlan_id)` -- look up VLAN in group
3. If not found, `nb.ipam.vlans.create(vid=vlan_id, name=name, group=group.id, ...)` -- create in group

**Confidence: HIGH**

### Fix 3: Scope VLAN Groups to SiteGroups (Enhancement)

**File:** `src/database/netbox_helpers.py`, method `get_or_create_vlan_group`

**Current:** Creates VLAN Groups without scope:
```python
vlan_group_data = {
    "name": group_name,
    "slug": _sanitize_slug(group_name),
}
```

**Recommended:** Add scope to tie group to SiteGroup:
```python
vlan_group_data = {
    "name": group_name,
    "slug": _sanitize_slug(group_name),
    "scope_type": "dcim.sitegroup",
    "scope_id": site_group_obj.id,
}
```

**Why:** This makes the VLAN Group formally scoped to its SiteGroup in NetBox's data model. Without it, the groups are "global" -- they work for uniqueness because VLANs are still separated by group, but the scope relationship is not visible in NetBox's UI or API responses.

**Note:** This requires looking up the SiteGroup object to get its ID. The `get_site()` helper already does this. The `get_or_create_vlan_group` method needs to accept a `site_group_id` parameter.

**Confidence: HIGH**

### Fix 4: Delete Operation VLAN Cleanup (Minor)

**File:** `src/database/netbox_crud_ops.py`, method `delete_one`

The delete operation (line 295-302) unconditionally deletes the VLAN after deleting the prefix. This is dangerous if the VLAN is shared by other prefixes (which should not happen after Fix 1, but defensive coding matters). Should use the existing `cleanup_unused_vlan()` pattern instead.

**Confidence: HIGH**

## Fields to Filter On to Avoid Cross-Site Collisions

| Operation | Required Filters | Why |
|-----------|-----------------|-----|
| Look up VLAN | `group_id` + `vid` | Ensures site-scoped uniqueness |
| Create VLAN | `group` (= group ID) + `vid` + `name` | Creates VLAN in correct group |
| Look up Prefix | `tenant_id` + `vrf_id` + `scope_type` + `scope_id` | Already correct in current code |
| Check VLAN exists | `group_id` + `vid` | Before create, check within group |

## NetBox Version Compatibility

| Feature | Min NetBox Version | Notes |
|---------|-------------------|-------|
| VLAN Groups | 2.0+ | Core feature, stable |
| VLAN Group scope (scope_type/scope_id) | 3.1+ | Generic foreign key scoping |
| Available VLANs endpoint | 3.2+ | `vlan_group.available_vlans` |
| Deprecation of VLAN.site field | 3.6+ | Use VLAN Groups instead |
| pynetbox 7.3.3 support | All above | Current version supports everything needed |

**Confidence: MEDIUM** (version numbers from training data, not verified against changelogs)

## Alternatives Considered

| Approach | Recommended? | Why / Why Not |
|----------|-------------|---------------|
| Filter VLANs by `group_id` + `vid` | **YES** | Correct NetBox pattern. VLAN Groups exist for exactly this purpose. |
| Filter VLANs by `site` field | NO | Deprecated in NetBox. Will be removed in future versions. |
| Use VLAN name as unique key | NO | Names are not inherently unique across groups. Two sites can have same EPG name. |
| Create separate VLAN objects per prefix | NO | Defeats purpose of VLAN Groups. Would create orphan VLANs. |
| Use `nb.ipam.vlans.filter()` instead of `.get()` | MAYBE | Safer when multiple results possible, but `.get(group_id=X, vid=Y)` should be unique within a group. Use `.filter()` as fallback if `.get()` raises on ambiguous results. |

## Installation

No new packages needed. The fix is purely in API call logic using existing pynetbox 7.3.3 capabilities.

```bash
# Existing dependencies -- no changes
pip install -r requirements.txt
```

## Sources

- [NetBox VLAN Groups Documentation](https://netboxlabs.com/docs/netbox/models/ipam/vlangroup/) -- VLAN Group scoping model, scope_type/scope_id fields
- [NetBox VLANs Documentation](https://netboxlabs.com/docs/netbox/models/ipam/vlan/) -- VLAN uniqueness constraints, group assignment
- [NetBox VLAN Management Overview](https://netboxlabs.com/docs/netbox/en/stable/features/vlan-management/) -- High-level VLAN management patterns
- [pynetbox IPAM Documentation](https://pynetbox.readthedocs.io/en/stable/IPAM.html) -- pynetbox API for VLAN operations
- [NetBox Issue #9203: Remove uniqueness of VLAN name within a group](https://github.com/netbox-community/netbox/issues/9203) -- Confirms uniqueness is (group, vid) AND (group, name)
- [NetBox Issue #19707: VLAN Uniqueness checking in a Site](https://github.com/netbox-community/netbox/issues/19707) -- Confirms uniqueness is per-group, not per-site
- [NetBox Discussion #11639: Same VLAN ID with different subnets](https://github.com/netbox-community/netbox/discussions/11639) -- Community patterns for multi-site VLAN management
- [pynetbox Issue #427: Available VLANs endpoint](https://github.com/netbox-community/pynetbox/issues/427) -- available_vlans detail endpoint support
- [pynetbox examples](https://gist.github.com/awfki/9884c85fa7cc9699de4001662c63646c) -- Practical pynetbox VLAN filter examples
