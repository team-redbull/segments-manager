# Project Research Summary

**Project:** Segments Manager — VLAN Scoping Bug Fix + Validation Layer Rationalization
**Domain:** NetBox IPAM integration — Python/FastAPI production application
**Researched:** 2026-03-27
**Confidence:** HIGH

## Executive Summary

The Segments Manager has two independent problems that research has fully characterized. The first is a critical data-integrity bug: VLAN lookups in `netbox_helpers.py:get_or_create_vlan()` search by VID alone with no group scoping, causing different sites to share a single NetBox VLAN object when they use the same VID. This silently corrupts the IPAM database — two prefixes in different sites end up referencing the same VLAN, EPG name changes on one site overwrite the other, and the NetBox UI shows incorrect associations. The fix is surgically contained to one method: resolve the VLAN Group first, then look up by `(group_id, vid)` instead of `(vid)` alone. No stack changes are needed; pynetbox 7.3.3 already supports the required filter parameters.

The second problem is that the validation layer (~888 lines across 5 modules) was built with a threat model appropriate for a public-facing web application, not an internal network management tool. This creates unnecessary friction: operators cannot use CIDR notation (`192.168.1.0/24`) as EPG names, cannot create `/30` point-to-point links, and are blocked by XSS and NoSQL injection validators that have no real threat to defend against in this context. Research identifies a ~34% reduction in validation code achievable by removing dead code, wrong-threat-model checks, and overly strict format validators — while keeping all validators that protect NetBox data integrity.

The key risk for the VLAN scoping fix is existing production data: VLANs created under the current buggy code are unscoped (no VLAN Group assignment). A naive fix that only adds group-scoped lookups will miss these existing VLANs, create duplicates, and orphan the originals. The fix must include a migration path — detect unscoped VLANs and assign them to the correct group rather than creating new ones. The key risk for validation relaxation is that removing XSS checks opens a stored XSS vector if the frontend uses `innerHTML`; frontend output escaping must be audited before server-side input checks are removed.

## Key Findings

### Recommended Stack

No stack changes are required for either fix. The existing stack — Python 3.11, FastAPI 0.104.1, pynetbox 7.3.3, Pydantic 2.5.0 — fully supports all required operations. The pynetbox `nb.ipam.vlans.get(group_id=X, vid=Y)` filter needed for the bug fix is available in the current version.

**Core technologies:**
- pynetbox 7.3.3: NetBox API client — `get(group_id=X, vid=Y)` and `create(group=group_id, ...)` are the two calls that fix the scoping bug
- FastAPI 0.104.1: Web framework — no changes needed, validation changes are below the API layer
- Pydantic 2.5.0: Data models — minor update to `Segment` model field descriptions/examples to reflect relaxed EPG name format

### Expected Features

The research reframes "features" as "what the validated system should accept." The core operator requests are CIDR-format EPG names and `/30` subnet support.

**Must have (table stakes — keep these validators):**
- Site validation against configured sites list — NetBox does not enforce this mapping
- VRF existence check — prevents orphaned prefixes with invalid VRF references
- VLAN ID range 1-4094 — IEEE 802.1Q spec, also enforced by NetBox
- Segment CIDR format + strict network address + site-prefix enforcement — core business logic not enforced by NetBox
- IP overlap detection — prevents conflicting subnets within the same VRF+site scope
- EPG name uniqueness per (VRF, site) — business rule not natively enforced by NetBox

**Should have (relaxations that reduce friction):**
- EPG name regex: relax from `^[a-zA-Z0-9_\-]+$` to `^[a-zA-Z0-9._/\-]+$` — allows CIDR notation and dotted hierarchical names
- Subnet mask range: expand from `/16-/29` to `/8-/30` — covers point-to-point links and large enterprise networks
- Remove `validate_network_broadcast_gateway`: blocks legitimate `/30` and `/31` subnets valid per RFC 3021

**Defer (v2+):**
- Cluster name max length increase to 253 chars (FQDN max) — current 100-char limit works for known use cases
- `validate_concurrent_modification` resurrection — dead code currently; resurrect only if concurrent access becomes a real operational problem

**Remove entirely (wrong threat model or dead code):**
- `security_validators.py` (121 lines) — XSS, path traversal, rate limit checks; wrong threat model for internal tool + dead code
- `validate_no_reserved_ips` — IPAM tool should not second-guess legitimate documentation of reserved ranges
- MongoDB-style injection checks (`$`, `.` keys, `__proto__`, `constructor`) in `validate_update_data` — no NoSQL in the stack
- `validate_json_serializable`, `validate_timezone_aware_datetime` — defensive checks for app bugs, not user input
- `validate_csv_row_data` — pure indirection wrapper; inline the check in the CSV import service

### Architecture Approach

The VLAN scoping fix is contained entirely within `src/database/netbox_helpers.py`. The structural change inverts the operation order in `get_or_create_vlan()`: resolve VLAN Group first, then search within that group. The current complex "VLAN exists" branch (lines 197-227) that tries to reassign groups after the fact becomes unnecessary and can be deleted, making the method roughly half its current size.

**Major components and change scope:**
1. `netbox_helpers.py:get_or_create_vlan()` — PRIMARY change: group-first lookup, remove group-reassignment branch, add migration path for existing unscoped VLANs
2. `netbox_helpers.py:get_or_create_vlan_group()` — MINOR enhancement: add `scope_type="dcim.sitegroup"` + `scope_id` to formally scope groups to SiteGroups in NetBox
3. `netbox_crud_ops.py:delete_one()` — MINOR fix: replace direct VLAN delete with `cleanup_unused_vlan()` pattern
4. `src/utils/validators/` (5 modules) — validation rationalization: delete `security_validators.py`, relax regex in `input_validators.py`, shrink `network_validators.py` and `data_validators.py`
5. `segment_service.py` — remove two XSS validator call sites (lines 34, 37) after frontend audit

### Critical Pitfalls

1. **Orphaned unscoped VLANs in production data** — The fix must detect existing unscoped VLANs and migrate them into the correct VLAN Group rather than creating duplicates. Use: try group-scoped lookup first; if not found, try global lookup by `(vid, tenant)`; if found globally but unscoped, assign to the correct group; only create new if nothing found anywhere. After deploy, verify with `nb.ipam.vlans.filter(group__isnull=True, tenant="RedBull")`.

2. **Cache serving stale data during VLAN migration** — `cleanup_unused_vlan()` relies on cached prefix data to decide if deletion is safe. After group reassignment operations, invalidate BOTH `CACHE_KEY_PREFIXES` and `CACHE_KEY_VLANS`. Invalidate at the START of migration operations, not just the end.

3. **Race condition on concurrent VLAN creation** — Two concurrent requests for the same VID+site can both fail to find the VLAN (not yet committed) and try to create it simultaneously. Implement the standard get-or-create-with-retry pattern: GET → if not found, CREATE → if CREATE fails with uniqueness error, GET again.

4. **CIDR EPG names rejected by NetBox without clear error** — The forward slash in `192.168.1.0/24` may be accepted or rejected depending on NetBox version. Test the relaxed regex against the actual target NetBox instance before removing the strict validator. Add error translation in `error_handlers.py` to convert pynetbox validation errors to user-friendly messages.

5. **XSS vector opened if frontend uses innerHTML** — Audit `static/js/app.js` for `innerHTML`, `document.write()`, jQuery `.html()` usage before removing server-side XSS checks. Replace with `textContent`. The removal sequence must be: audit frontend → fix escaping → then remove server validators.

## Implications for Roadmap

Based on research, the two fixes are independent and can be sequenced or parallelized. The VLAN scoping fix has higher urgency (active data corruption) and higher complexity (migration required). The validation relaxation has lower risk and immediate operator impact.

### Phase 1: VLAN Scoping Fix (Critical Bug)
**Rationale:** Active data corruption in production. Every segment creation that reuses a VID across sites worsens the problem. Must ship before validation changes.
**Delivers:** Correct per-site VLAN isolation. Each (site, VRF, VID) combination gets its own NetBox VLAN object. Existing shared VLANs migrated to correct groups.
**Addresses:** Core correctness — two sites can safely use the same VLAN ID
**Avoids:** Pitfall 1 (orphaned VLANs), Pitfall 2 (cache stale data), Pitfall 3 (race condition), Pitfall 6 (delete kills shared VLANs), Pitfall 7 (site slug capitalization)

**Key implementation steps:**
1. Fix `get_or_create_vlan()` — group-first lookup with migration fallback for unscoped VLANs
2. Fix `get_or_create_vlan_group()` — add `scope_type`/`scope_id` for proper SiteGroup scoping
3. Fix `delete_one()` — use `cleanup_unused_vlan()` instead of direct VLAN delete
4. Add VLAN cache keyed by `(group_id, vid)` — optional performance improvement
5. Add tests: same VID in two sites must produce two separate VLAN objects

### Phase 2: Validation Layer Rationalization
**Rationale:** Unblocks operators who need CIDR-format EPG names and `/30` subnets. Lower risk than Phase 1 — changes only affect input validation, not data storage.
**Delivers:** Relaxed EPG name format (allows dots and slashes), expanded subnet mask range, ~34% reduction in validation code, removal of dead/wrong-threat-model code.
**Uses:** Existing validation framework — changes are to individual validators, not the architecture
**Implements:** FEATURES.md MVP recommendation order: EPG name regex → XSS removal → dead code removal → subnet mask → NoSQL injection → reserved IP check

**Key implementation steps:**
1. Audit `static/js/app.js` for `innerHTML` usage — verify output escaping is safe BEFORE removing server XSS checks
2. Relax EPG name regex in `input_validators.py` line 63 — test against target NetBox instance first
3. Remove `validate_no_script_injection` calls from `segment_service.py` lines 34, 37
4. Delete `security_validators.py` entirely (121 lines — all dead or wrong-model code)
5. Remove dead validators: `sanitize_input`, `validate_no_path_traversal`, `validate_rate_limit_data`, `validate_concurrent_modification`, `validate_json_serializable`, `validate_timezone_aware_datetime`
6. Relax subnet mask range, remove `validate_network_broadcast_gateway`
7. Remove NoSQL injection checks from `validate_update_data`
8. Add tests for relaxed validation: CIDR EPG names accepted, `/30` subnets accepted, invalid chars still rejected

### Phase Ordering Rationale

- Phase 1 before Phase 2 because the scoping bug causes active data corruption; validation relaxation is a UX improvement
- Within Phase 1, group resolution must be fixed before VLAN lookup, which must be fixed before delete cleanup
- Within Phase 2, the frontend XSS audit must complete before server-side XSS validation is removed — this is a hard dependency
- Both phases need new tests added alongside code changes, not after

### Research Flags

Phases needing care during implementation:
- **Phase 1:** Production data migration — test against a NetBox instance with existing segments before deploying. The migration path in `get_or_create_vlan()` must handle the case where existing VLANs have no group assignment.
- **Phase 2, XSS removal:** Frontend audit required first. This is well-understood work but the audit could surface `innerHTML` usage that needs fixing.

Phases with standard patterns (no additional research needed):
- **Phase 2, dead code removal:** Mechanical deletion of unused validators. Standard refactoring.
- **Phase 2, regex relaxation:** One-line change in `input_validators.py`. Verify against NetBox before shipping.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | No stack changes. pynetbox 7.3.3 filter syntax verified against docs and pynetbox GitHub |
| Features | HIGH | Validator analysis is direct code inspection. EPG naming patterns from Cisco official docs + NetBox issue threads |
| Architecture | HIGH | Root cause identified by direct code analysis. Fix approach verified against NetBox VLAN Group data model |
| Pitfalls | HIGH | All critical pitfalls derived from direct code analysis of production codebase. Cache and race condition behaviors are well-understood |

**Overall confidence:** HIGH

### Gaps to Address

- **NetBox version for `/` in VLAN names:** The FEATURES.md research notes that NetBox's acceptance of forward slashes in VLAN names depends on version. The recommendation is to test the relaxed regex against the actual target NetBox instance before deploying. If slash is rejected, the fallback is to reject slash-containing names with a clear user message.
- **Site slug capitalization:** `get_or_create_vlan()` line 183 capitalizes site slugs. Pitfall 7 flags that if NetBox stores slugs in lowercase, VLAN Group lookups will fail. During Phase 1 implementation, verify what form the `get_site()` helper returns and normalize consistently in ONE place.
- **Existing shared VLAN objects:** Research cannot determine how many VLANs in the production NetBox instance are currently shared across sites. The migration path in Phase 1 handles this, but the scope of existing corruption is unknown until the query `nb.ipam.vlans.filter(group__isnull=True, tenant="RedBull")` is run.

## Sources

### Primary (HIGH confidence)
- [NetBox VLAN Groups Documentation](https://netboxlabs.com/docs/netbox/models/ipam/vlangroup/) — VLAN Group scoping model, scope_type/scope_id fields
- [NetBox VLANs Documentation](https://netboxlabs.com/docs/netbox/models/ipam/vlan/) — VLAN uniqueness constraints, group assignment
- [pynetbox IPAM Documentation](https://pynetbox.readthedocs.io/en/stable/IPAM.html) — pynetbox API for VLAN operations
- [Cisco ACI Naming Convention Best Practices](https://www.cisco.com/c/dam/en/us/solutions/collateral/data-center-virtualization/application-centric-infrastructure/aci-guide-naming-convention-best-practices.pdf) — EPG naming character constraints
- Direct code analysis of production codebase at `src/database/netbox_helpers.py`, `netbox_crud_ops.py`, `src/utils/validators/`

### Secondary (MEDIUM confidence)
- [NetBox Issue #9203](https://github.com/netbox-community/netbox/issues/9203) — VLAN uniqueness is `(group, vid)` AND `(group, name)`
- [NetBox Issue #19707](https://github.com/netbox-community/netbox/issues/19707) — uniqueness is per-group, not per-site
- [NetBox VLAN name field discussion #6349](https://github.com/netbox-community/netbox/issues/6349) — max_length=64, no character regex in Django model
- [RFC 3021](https://datatracker.ietf.org/doc/html/rfc3021) — Using /31 prefix length for point-to-point links
- [pynetbox examples gist](https://gist.github.com/awfki/9884c85fa7cc9699de4001662c63646c) — Practical pynetbox VLAN filter examples

### Tertiary (MEDIUM confidence, version-dependent)
- NetBox version compatibility table for `scope_type`/`scope_id` on VLAN Groups (min NetBox 3.1+) — needs validation against target instance version

---
*Research completed: 2026-03-27*
*Ready for roadmap: yes*
