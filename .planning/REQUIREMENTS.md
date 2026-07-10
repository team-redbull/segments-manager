# Requirements: Segments Manager

**Defined:** 2026-03-27
**Core Value:** Operators can create, allocate, and search VLANs and prefixes across any VRF+Site combination without polluting each other's data in NetBox.

## v1 Requirements

### VLAN Scoping Fix

- [x] **VLAN-01**: VLANs are looked up and created scoped to their VLAN Group (group_id + vid), not globally by vid alone
- [x] **VLAN-02**: Two segments with the same VLAN ID in different sites under the same VRF do not share a NetBox VLAN object
- [x] **VLAN-03**: EPG name search returns only results from the correct site — no cross-site contamination
- [x] **VLAN-04**: Existing production VLANs are assessed for unscoped state before deployment (migration audit query documented)
- [x] **VLAN-05**: Group-reassignment fallback logic removed from `get_or_create_vlan()` (~30 lines of complexity eliminated)

### Validation — Removal

- [x] **VAL-01**: `security_validators.py` module deleted entirely (XSS, path traversal, rate limit — dead code with wrong threat model for internal tool)
- [x] **VAL-02**: NoSQL injection checks removed (`$` key detection, `__proto__`/`constructor` blocklist — MongoDB patterns irrelevant to pynetbox REST backend)
- [x] **VAL-03**: Dead code validators removed: `sanitize_input`, `validate_no_path_traversal`, `validate_rate_limit_data`, `validate_concurrent_modification`, `validate_json_serializable`, `validate_timezone_aware_datetime`
- [x] **VAL-04**: All call sites for removed validators cleaned up (no broken imports or dead calls in services)

### Validation — Relaxation

- [x] **VAL-05**: EPG name regex updated to accept dots and forward slashes (allows CIDR format like `192.168.1.0/24`)
- [x] **VAL-06**: Subnet mask range expanded to /16–/31 (adds /30 and /31 for point-to-point links per RFC 3021)

## v2 Requirements

### Optional Enhancements (deferred)

- **ENH-01**: VLAN Group `scope_type`/`scope_id` set to SiteGroup when creating new VLAN Groups (requires NetBox 3.1+, low priority)
- **ENH-02**: Per-group VLAN cache keyed by `(group_id, vid)` for improved cache hit rate

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full data migration of existing shared VLANs | Risk too high for automation; manual remediation if needed after audit |
| Remove reserved IP validation (`validate_no_reserved_ips`) | Business rule, not a duplicate of NetBox — loopback/link-local prefixes should stay blocked |
| Remove overlap detection | Data integrity check, not friction — prevents real corruption |
| Remove VRF existence validation | Prevents creating segments against non-existent VRFs |
| Frontend XSS audit / innerHTML review | Out of scope for this milestone; do before any future XSS removal from templates |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VLAN-01 | Phase 1 | Complete |
| VLAN-02 | Phase 1 | Complete |
| VLAN-03 | Phase 1 | Complete |
| VLAN-04 | Phase 1 | Complete |
| VLAN-05 | Phase 1 | Complete |
| VAL-01 | Phase 2 | Complete |
| VAL-02 | Phase 2 | Complete |
| VAL-03 | Phase 2 | Complete |
| VAL-04 | Phase 2 | Complete |
| VAL-05 | Phase 2 | Complete |
| VAL-06 | Phase 2 | Complete |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after initial definition*
