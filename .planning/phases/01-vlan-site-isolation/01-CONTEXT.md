# Phase 1: VLAN Site Isolation - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix `get_or_create_vlan()` in `src/database/netbox_helpers.py` so every site+VID pair gets its own independent NetBox VLAN object, scoped to the correct VLAN Group. Two sites using the same VLAN ID must never share a VLAN object. This is a backend data-layer fix — no API contracts or UI change.

</domain>

<decisions>
## Implementation Decisions

### Existing unscoped VLANs
- The app must NOT touch existing unscoped VLANs in NetBox — leave them as-is
- No auto-reassignment, no auto-migration, no auto-delete
- Operator (user) will manually remediate by: deleting the affected segments via Segments Manager and recreating them — the recreate path will produce properly scoped VLANs
- The fix only affects new writes; reads of legacy unscoped VLANs are out of scope

### Audit query
- A query to find unscoped VLANs (e.g., `nb.ipam.vlans.filter(group__isnull=True, tenant="Redbull")`) must be included in the codebase
- Location: as a comment or script in the repo so it can be found and rerun, not just in a PR description
- Purpose: operator runs this before deploying to know what needs manual remediation

### Claude's Discretion
- Error behavior when VLAN Group not found (hard fail vs warning) — Claude decides
- Exact placement of audit query in codebase (README section, inline comment, standalone script)
- Whether to log a warning when a legacy unscoped VLAN is encountered during a read (non-breaking)

</decisions>

<specifics>
## Specific Ideas

- Remediation path: delete segment via Segments Manager UI/API → recreate — this naturally produces a properly scoped VLAN via the fixed code path
- Audit query target: VLANs where `group` is null AND tenant is "Redbull" (to scope to this app's data)

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-vlan-site-isolation*
*Context gathered: 2026-03-27*
