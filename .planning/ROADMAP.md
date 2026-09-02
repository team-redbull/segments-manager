# Roadmap: Segments Manager

## Overview

This milestone fixes two independent problems in the Segments Manager. Phase 1 eliminates an active data-corruption bug where VLAN objects are shared across sites instead of being scoped to their VLAN Group. Phase 2 rationalizes the validation layer by removing dead code, wrong-threat-model checks, and overly strict validators that block legitimate operator workflows. Phase 1 ships first because every segment creation that reuses a VID across sites worsens the corruption.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: VLAN Site Isolation** - Fix VLAN scoping so each site gets its own VLAN object per VID (completed 2026-03-27)
- [ ] **Phase 2: Validation Rationalization** - Remove dead/wrong-model validators and relax overly strict input rules

## Phase Details

### Phase 1: VLAN Site Isolation

**Goal**: Two sites using the same VLAN ID under the same VRF each get their own independent NetBox VLAN object -- no shared state, no cross-site contamination

**Depends on**: Nothing (first phase)

**Requirements**: VLAN-01, VLAN-02, VLAN-03, VLAN-04, VLAN-05

**Success Criteria** (what must be TRUE):

1. Creating a segment with VLAN ID 100 in site1/VRF1 and another with VLAN ID 100 in site2/VRF1 produces two separate NetBox VLAN objects, each in its own VLAN Group
2. Searching for an EPG name returns only segments from the queried site -- no results from other sites that happen to share the same VLAN ID
3. Changing the EPG name on a segment in site1 does not affect the EPG name of a segment with the same VLAN ID in site2
4. A documented audit query exists that operators can run against production NetBox to identify any existing unscoped VLANs before deployment
5. The group-reassignment fallback branch in get_or_create_vlan() is gone -- the method resolves the VLAN Group first, then looks up by (group_id, vid)

**Plans**: 1 plan

Plans:

- [ ] 01-01-PLAN.md — Rewrite get_or_create_vlan() with group-first scoped lookup + audit script

### Phase 2: Validation Rationalization

**Goal**: Operators can use CIDR-format EPG names and /30 subnets, and the validation layer contains only checks that protect NetBox data integrity -- no XSS, no NoSQL injection, no dead code

**Depends on**: Phase 1

**Requirements**: VAL-01, VAL-02, VAL-03, VAL-04, VAL-05, VAL-06

**Success Criteria** (what must be TRUE):

1. An operator can create a segment with EPG name `192.168.1.0/24` (dots and forward slashes accepted)
2. An operator can create a segment with a /30 or /31 subnet mask for point-to-point links
3. The `security_validators.py` module no longer exists in the codebase, and no imports reference it
4. No validator function in the codebase checks for NoSQL injection patterns (`$`, `__proto__`, `constructor`) or performs XSS sanitization
5. All remaining validators have live call sites -- no dead validator functions exist

**Plans**: 2 plans

Plans:

- [ ] 02-01-PLAN.md — Delete security_validators.py and remove all dead validators (VAL-01, VAL-02, VAL-03, VAL-04)
- [ ] 02-02-PLAN.md — Relax EPG name regex and expand subnet mask range to /31 (VAL-05, VAL-06)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3

| Phase | Plans Complete | Status | Completed |
|---|---|---|---|
| 1. VLAN Site Isolation | 1/1 | Complete | 2026-03-27 |
| 2. Validation Rationalization | 2/2 | Complete | 2026-03-28 |
| 3. Database Layer Refactor | 2/2 | Complete   | 2026-03-28 |

### Phase 3: Database Layer Refactor

**Goal:** Collapse the 9-file over-engineered database module into a clean 7-file domain-named structure — remove the MongoDB abstraction layer, eliminate dead code, fix misleading names. All existing behaviour preserved exactly.
**Depends on:** Phase 2
**Plans:** 2/2 plans complete

Plans:

- [ ] 03-01-PLAN.md — Refactor src/database/ internals: create netbox_segments.py + netbox_objects.py, trim dead code, delete 3 old files
- [ ] 03-02-PLAN.md — Update callers in src/utils/database/ and validators to use domain functions (no MongoDB syntax)
