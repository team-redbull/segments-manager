# Feature Landscape: Validation Layer Rationalization

**Domain:** Internal NetBox IPAM management tool -- validation philosophy
**Researched:** 2026-03-27
**Mode:** Ecosystem (validation philosophy for internal network tooling)

## Context

The Segments Manager has a validation layer split across 5 modules (~700+ lines) in `src/utils/validators/`. The team wants to reduce friction for internal operators by relaxing overly strict validators. This document categorizes every validator as KEEP, RELAX, or REMOVE, with specific rationale grounded in network engineering conventions and the "NetBox is source of truth" principle.

---

## Table Stakes: Validators That Must Stay

These validators protect data integrity in NetBox. Removing them risks corrupting the IPAM database or creating nonsensical network objects.

| Validator | Module | Why It Must Stay | Complexity to Keep |
|-----------|--------|------------------|-------------------|
| `validate_site` | input_validators | Prevents creating segments for non-existent sites. NetBox would accept the data but it would be orphaned. App-level concern (configured sites list). | Low (already clean) |
| `validate_vrf` | organization_validators | Async check that VRF exists in NetBox. Without this, segments get created referencing non-existent VRFs, causing lookup failures. | Low |
| `validate_vlan_id` | input_validators | Range 1-4094 is IEEE 802.1Q spec. Pydantic already enforces `ge=1, le=4094` on the model, but the explicit validator adds a VLAN 1 warning (reserved). NetBox also enforces VID range. | Low |
| `validate_segment_format` | network_validators | Validates CIDR format, strict network address (not host address), and site-prefix enforcement. This is core business logic -- site1 must use 192.x.x.x. NetBox does NOT enforce this mapping. | Low |
| `validate_ip_overlap` | network_validators | Prevents overlapping subnets within the same scope. NetBox has optional overlap detection but Segments Manager enforces stricter per-VRF+site rules. Critical for data integrity. | Low |
| `validate_vlan_name_uniqueness` | organization_validators | Prevents EPG name conflicts within the same (VRF, site) scope. This is business logic NetBox does not enforce natively (NetBox enforces uniqueness within VLAN Groups, but the mapping is app-managed). | Low |
| `validate_segment_not_allocated` | organization_validators | Prevents deleting segments that are in use. Pure business rule, not enforced by NetBox. | Low |
| `validate_object_id` | input_validators | Basic null/empty check on IDs before database lookups. Prevents unnecessary API calls. | Low |

## Validators to Relax

These validators are too restrictive for the actual use cases of network operators. They should be loosened, not removed.

| Validator | Module | Current Behavior | Proposed Change | Rationale |
|-----------|--------|-----------------|-----------------|-----------|
| `validate_epg_name` | input_validators | Regex `^[a-zA-Z0-9_\-]+$` -- blocks dots, slashes, spaces | Change to `^[a-zA-Z0-9._/\-]+$` -- allow dots, forward slashes | See "EPG Name Format" section below. Operators use CIDR-format names like `192.168.1.0/24` and dotted names like `prod.web.tier1`. NetBox VLAN name field is a CharField with max_length=64 and no character regex -- it accepts dots and slashes. |
| `validate_subnet_mask` | network_validators | Rejects anything outside /16 to /29 | Expand to /8 to /30, or remove and let NetBox handle | /30 is common for point-to-point links. /8-/15 are legitimate in large enterprise networks. The current range is opinionated for a "typical datacenter" but this is a tool for network engineers who know what they are doing. |
| `validate_network_broadcast_gateway` | network_validators | Rejects networks with fewer than 4 addresses (blocks /30, /31) | Remove or relax to allow /30 and /31 | /30 is standard for point-to-point links (2 usable IPs). /31 is valid per RFC 3021 for point-to-point. Network engineers expect to use these. |
| `validate_cluster_name` | input_validators | Regex `^[a-zA-Z0-9_\-\.]+$`, max 100 chars | Keep regex but bump max to 253 chars (FQDN max) | Cluster names can be FQDNs. 100 chars is already generous but 253 matches the DNS spec. Low priority change. |
| `validate_description` | input_validators | Max 500 chars, blocks control characters | Keep control char check, increase max to 1000 | 500 is reasonable but operators sometimes paste config snippets. Control char check is fine -- prevents null bytes and other garbage. |
| `validate_update_data` (NoSQL injection check) | data_validators | Blocks keys containing `$` or `.` | Remove the `$` and `.` key check | This was copied from MongoDB patterns. NetBox is a REST API, not MongoDB. There is no NoSQL injection vector. The `$` check is a false pattern. The `.` check actively blocks legitimate field names. |
| `validate_update_data` (`__proto__`, `constructor` check) | data_validators | Blocks keys like `__proto__`, `constructor` | Remove | Prototype pollution is a JavaScript/Node.js concern. This is a Python/FastAPI app talking to a REST API. No risk. |

## Validators to Remove Entirely

These validators add friction without protecting against real threats in an internal tool.

| Validator | Module | Why Remove |
|-----------|--------|-----------|
| `validate_no_script_injection` | security_validators | XSS prevention for an internal network management tool used by trusted operators. The web UI should handle output encoding (which is the proper defense), not input rejection. This validator blocks legitimate inputs containing `<`, `(`, and other characters that might appear in descriptions. **Called on both `epg_name` and `description` fields in `segment_service.py` lines 34, 37.** |
| `sanitize_input` | security_validators | Not actually called anywhere in the service layer (dead code). Only defined. Remove. |
| `validate_no_path_traversal` | security_validators | Not called anywhere in the service layer (dead code based on grep results). Even if it were, path traversal is not a concern -- the app does not serve user-specified file paths. |
| `validate_rate_limit_data` | security_validators | Dead code. Not called anywhere. Rate limiting should be at the reverse proxy/API gateway level, not validated as a data structure. |
| `validate_no_reserved_ips` | network_validators | Blocks loopback (127.x), link-local (169.254.x), multicast (224+). While well-intentioned, network engineers may legitimately need to document these ranges in IPAM. NetBox accepts all valid IP ranges. An IPAM tool should not second-guess which IPs are "allowed". The site-prefix validation already constrains the first octet. |
| `validate_json_serializable` | data_validators | Defensive programming that catches bugs in the app's own code, not user input issues. If the app produces non-serializable data, that is a bug to fix in the code, not a runtime validation to enforce. Adds complexity without value. |
| `validate_timezone_aware_datetime` | data_validators | Same as above -- this validates internal datetime handling, not user input. If datetimes are naive, fix the code that creates them. |
| `validate_concurrent_modification` | organization_validators | Optimistic locking check. Currently dead code (grep shows it is only defined in the validators module and exported in `__init__.py` but never called from any service). If needed later, it should be in the database layer, not in validators. |
| `validate_csv_row_data` | data_validators | Delegates entirely to `InputValidators` methods. Once EPG name validation is relaxed, this just adds an extra layer of indirection. Consider inlining the required-field check into the CSV import service directly. |

---

## EPG Name Format: Network Engineering Conventions

This is the core question: what characters should EPG names support?

### Research Findings

**Cisco ACI EPG Naming (official Cisco best practices):**
- Recommended delimiter: underscore `_` (never used by ACI system internally, so no conflicts)
- Example patterns: `Web_EPG`, `Vl101_EPG`, `Mgmt_EPG`, `DC_L3EPG`
- Custom EPG names can be up to 80 characters (VMware vCenter) or 61 characters (SCVMM)
- Special characters count as 3x normal character length in ACI
- **Confidence: HIGH** (Cisco official documentation)

**Real-world EPG/VLAN naming patterns observed across organizations:**
- Function-based: `PROD_WEB`, `DEV_DB`, `MGMT_OOB`
- VLAN-ID-based: `VLAN100`, `Vl_100`
- Subnet-based: `192.168.1.0_24` (using underscore instead of slash)
- CIDR-based: `192.168.1.0/24` (using actual CIDR notation as the name)
- Hybrid: `PROD_192.168.1.0_24`
- **Confidence: MEDIUM** (based on operational patterns, not formal documentation)

**NetBox VLAN name field:**
- Django CharField, max_length=64
- No character regex validation in the model -- accepts any printable characters including dots, slashes, spaces
- Uniqueness enforced within VLAN Group scope (name + VID must be unique per group)
- **Confidence: MEDIUM** (based on NetBox issue discussions and model patterns; could not access source directly)

### Recommendation

Relax the EPG name regex from `^[a-zA-Z0-9_\-]+$` to:

```
^[a-zA-Z0-9._/\-]+$
```

This allows:
- `192.168.1.0/24` -- CIDR notation (the operator's primary request)
- `prod.web.tier1` -- dotted hierarchical names
- `PROD_WEB-01` -- existing alphanumeric+underscore+hyphen patterns
- `10.0.0.0/8` -- large network documentation

This still blocks:
- Spaces (common source of subtle bugs in scripts that parse VLAN names)
- Special characters like `<`, `>`, `&`, `"`, `'` (not needed in network names)
- Null bytes, control characters

**Why not remove the regex entirely and let NetBox validate?** Because the EPG name maps to the VLAN name in NetBox, and while NetBox accepts nearly anything, downstream systems (switches, ACI fabric, automation scripts) may not. The relaxed regex covers all legitimate network engineering naming patterns without opening the door to garbage data.

---

## Anti-Features: Things to Explicitly NOT Build

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Output encoding in validators | Mixing concerns. Validators check input, not output. | Handle HTML encoding in the Jinja2/static templates (or use a framework that auto-escapes, which FastAPI + Jinja2 does by default). |
| Per-field rate limiting | Over-engineering for an internal tool. | Use reverse proxy rate limiting (nginx, HAProxy) if needed. |
| MongoDB-style injection protection | Wrong threat model. NetBox is a REST API. | Remove existing NoSQL injection checks. |
| Configurable validation rules | Adds complexity for something that should be stable. | Hardcode sensible defaults, change them in code when needed. |
| Validation middleware | Moving validation out of the service layer adds indirection. | Keep validation in `_validate_segment_data()` where it is explicit and visible. |

---

## Feature Dependencies

```
EPG name relaxation → Update validate_epg_name regex
                    → Update Pydantic model description/examples in schemas.py
                    → Update validate_csv_row_data (or inline it)
                    → Update UI help text if any

XSS removal → Remove validate_no_script_injection calls from segment_service.py (lines 34, 37)
            → Remove security_validators.py entirely (all methods are either dead code or being removed)
            → Remove SecurityValidators from __init__.py exports

Subnet mask relaxation → Update validate_subnet_mask range
                       → Update or remove validate_network_broadcast_gateway
                       → These are independent of EPG changes

NoSQL injection removal → Update validate_update_data in data_validators.py
                        → Remove $/./__proto__/constructor checks
                        → Independent of other changes

Dead code removal → Remove sanitize_input, validate_no_path_traversal, validate_rate_limit_data,
                    validate_concurrent_modification, validate_json_serializable,
                    validate_timezone_aware_datetime
                 → Can be done independently
```

## MVP Recommendation

Execute in this order (each change is independently deployable):

1. **Relax EPG name regex** -- highest operator impact, simplest change (one regex in `input_validators.py` line 63)
2. **Remove XSS validation calls** -- two lines in `segment_service.py`, then delete `security_validators.py`
3. **Remove dead code validators** -- clean sweep of unused validators across all modules
4. **Relax subnet mask range** -- expand /16-/29 to /8-/30 (or remove entirely)
5. **Remove NoSQL injection checks** -- clean up `validate_update_data`
6. **Remove reserved IP check** -- let operators document any IP range they need

Defer:
- `validate_concurrent_modification` resurrection: Only add back if concurrent access becomes a real problem. Currently dead code.
- Cluster name max length increase: Low impact, change when an actual FQDN exceeds 100 chars.

---

## Summary of Changes by Module

| Module | Current Lines | Action | Result |
|--------|--------------|--------|--------|
| `security_validators.py` | 121 lines | DELETE ENTIRELY | 0 lines |
| `input_validators.py` | 141 lines | Relax EPG regex (1 line change) | ~141 lines |
| `network_validators.py` | 254 lines | Remove `validate_no_reserved_ips` (47 lines), relax subnet mask, relax/remove broadcast check | ~170 lines |
| `organization_validators.py` | 139 lines | Remove dead `validate_concurrent_modification` (17 lines) | ~122 lines |
| `data_validators.py` | 166 lines | Remove JSON/timezone validators (~50 lines), remove NoSQL checks (~15 lines), consider inlining CSV validator | ~100 lines |
| `__init__.py` | 67 lines | Remove security exports, remove dead code exports | ~50 lines |
| **Total** | **~888 lines** | | **~583 lines (~34% reduction)** |

---

## Sources

- [Cisco ACI Naming Convention Best Practices](https://www.cisco.com/c/dam/en/us/solutions/collateral/data-center-virtualization/application-centric-infrastructure/aci-guide-naming-convention-best-practices.pdf) - Official Cisco document on EPG naming
- [Cisco ACI Object Naming and Numbering](https://www.cisco.com/c/en/us/td/docs/switches/datacenter/aci/apic/sw/kb/b-Cisco-ACI-Naming-and-Numbering.html) - Naming and numbering best practices
- [Custom EPG Name Configuration - Cisco ACI 6.0](https://www.cisco.com/c/en/us/td/docs/dcn/aci/apic/6x/virtualization/cisco-aci-virtualization-guide-60x/ACI-Virtualization-Guide-60x-custom-epg-name-configuration.html) - Custom EPG name character limits
- [NetBox VLAN name field discussion (Issue #6349)](https://github.com/netbox-community/netbox/issues/6349) - VLAN name max_length=64
- [NetBox VLAN Management docs](https://netboxlabs.com/docs/netbox/en/stable/features/vlan-management/) - VLAN model documentation
- [NetBox Custom Validation docs](https://netboxlabs.com/docs/netbox/en/stable/customization/custom-validation/) - NetBox's own validation framework
- [VLAN Management DeepWiki](https://deepwiki.com/netbox-community/netbox/4.2-vlan-and-vrf-management) - Model analysis
- [RFC 3021](https://datatracker.ietf.org/doc/html/rfc3021) - Using /31 prefix length for point-to-point links (referenced for subnet mask relaxation rationale)
