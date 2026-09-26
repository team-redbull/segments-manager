"""Segments Manager — MongoDB integration test suite.

Runs against a live server. See conftest.py for configuration.

Covers the decentralized, per-site MongoDB model:
  * no VRF anywhere (legacy `vrf` field is rejected)
  * VLAN IDs and EPG names are unique PER SITE
  * site IP-prefix enforcement, CIDR/subnet validation
  * atomic allocate / idempotent re-allocate / release
  * segment type as ALLOCATION state: none while Available, stamped on by
    allocate, cleared by release
  * auth enforcement on write endpoints
  * single-segment operations keyed by the segment CIDR (the natural key —
    unique + immutable); the ObjectId-based /segments/{id} routes are gone
"""

import uuid

import pytest
import requests

from conftest import (API, AUTH_HEADERS, TIMEOUT, next_vlan, cidr_for,
                      SITE_POOL_EXCEPTION)


def _uid(prefix="EPG"):
    return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Health & storage backend
# ---------------------------------------------------------------------------
class TestHealth:
    def test_health_ok_and_mongodb(self):
        r = requests.get(f"{API}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["storage_type"] == "mongodb"

    def test_sites_configured(self):
        r = requests.get(f"{API}/sites", timeout=TIMEOUT)
        assert r.status_code == 200
        assert "site1" in r.json()["sites"]


# ---------------------------------------------------------------------------
# Removed endpoints (VRF era)
# ---------------------------------------------------------------------------
class TestRemovedEndpoints:
    def test_vrfs_endpoint_gone(self):
        assert requests.get(f"{API}/vrfs", timeout=TIMEOUT).status_code == 404

    def test_network_site_mapping_gone(self):
        assert requests.get(f"{API}/network-site-mapping", timeout=TIMEOUT).status_code == 404

    def test_unlock_endpoint_gone(self):
        # Segments are born Available — there is nothing left to unlock.
        r = requests.post(f"{API}/segments/unlock", json={"segment": "192.10.1.0/24"},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404

    @pytest.mark.parametrize("path", ["segment-connectivity-requests",
                                      "segment-connectivity-failure"])
    def test_segment_connectivity_endpoints_gone(self, path):
        # The firewall workflow that published to these no longer exists.
        r = requests.put(f"{API}/segments/{path}",
                         json={"segment": "192.10.1.0/24", "request_ids": []},
                         headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404

    def test_type_conversion_endpoint_gone(self):
        # An Available segment has no type to convert — the type is stamped on
        # at allocation — so the convert-segment workflow and its endpoint went.
        r = requests.put(f"{API}/segments/type",
                         json={"segment": "192.10.1.0/24", "type": "MCE"},
                         headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class TestAuthRequired:
    def test_create_requires_auth(self):
        v = next_vlan()
        body = {"site": "site1", "vlan_id": v, "epg_name": _uid(),
                "segment": cidr_for("site1", v), "dhcp": False}
        assert requests.post(f"{API}/segments", json=body, timeout=TIMEOUT).status_code == 401

    def test_allocate_requires_auth(self):
        body = {"cluster_name": "noauth-cluster", "site": "site1", "type": "HC"}
        assert requests.post(f"{API}/segments/allocate", json=body, timeout=TIMEOUT).status_code == 401

    def test_delete_requires_auth(self):
        assert requests.delete(f"{API}/segments", params={"segment": "10.99.99.0/24"},
                               timeout=TIMEOUT).status_code == 401


# ---------------------------------------------------------------------------
# Segment validation
# ---------------------------------------------------------------------------
class TestSegmentValidation:
    def test_legacy_vrf_field_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v), vrf="Network1")
        assert r.status_code == 422  # extra="forbid"

    def test_vlan_id_out_of_range(self, segment_factory):
        r = segment_factory(site="site1", vlan_id=9999, epg_name=_uid(),
                            segment="192.10.50.0/24")
        assert r.status_code == 422

    def test_invalid_site(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="does-not-exist", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        assert r.status_code in (400, 422)

    def test_segment_from_another_sites_pool_rejected(self, segment_factory):
        v = next_vlan()
        # site2's pool is a different /16 entirely
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site2", v))
        assert r.status_code == 400

    def test_segment_outside_pool_same_first_octet_rejected(self, segment_factory):
        """The case the old first-octet rule wrongly accepted.

        site1's pool is 192.10.0.0/16, so 192.99.x is the right first octet but
        the wrong /16. Under the previous `first_octet == "192"` check this was
        allowed straight through.
        """
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="192.99.0.0/24")
        assert r.status_code == 400
        assert "outside site" in r.json()["detail"]

    def test_subnet_of_a_listed_exception_is_still_rejected(self, segment_factory):
        """`pool-exceptions` is exact-match, not subnet_of: one listed /22 must
        not quietly authorise the four /24s inside it.

        Ordered before the test that creates the /22 so a leaked one from an
        earlier session cannot turn this into an overlap failure — though
        containment runs before the overlap check either way, which is why the
        detail is asserted too.
        """
        r = segment_factory(site="site1", vlan_id=next_vlan(), epg_name=_uid(),
                            segment="172.20.5.0/24")
        assert r.status_code == 400, r.text
        assert "outside site" in r.json()["detail"]

    def test_exception_does_not_travel_to_another_site(self, segment_factory):
        """The list is per-site: site1's exemption says nothing about site2."""
        r = segment_factory(site="site2", vlan_id=next_vlan(), epg_name=_uid(),
                            segment=SITE_POOL_EXCEPTION["site1"])
        assert r.status_code == 400, r.text
        assert "outside site" in r.json()["detail"]

    def test_listed_out_of_pool_segment_is_accepted(self, segment_factory):
        """The escape hatch itself: a CIDR outside site1's /16 pool is created
        because it is listed verbatim in that site's pool-exceptions."""
        r = segment_factory(site="site1", vlan_id=next_vlan(), epg_name=_uid(),
                            segment=SITE_POOL_EXCEPTION["site1"])
        assert r.status_code == 200, r.text

    def test_ipv6_segment_rejected(self, segment_factory):
        """`segment` is an unvalidated string on the request model, so an IPv6
        CIDR reaches the validator from any caller. It must be a 400 naming the
        address family — not a 500, and not a misleading "outside the pool"."""
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="2001:db8::/48")
        assert r.status_code == 400
        assert "Only IPv4" in r.json()["detail"]

    def test_non_network_address_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="192.10.1.5/24")  # host address, not network
        assert r.status_code == 400
        # Must fail on the network-address rule, not on pool containment
        assert "network address" in r.json()["detail"]

    def test_missing_mask_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="192.10.1.0")  # no /mask
        assert r.status_code == 400
        assert "subnet mask" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Segment type (MCE / INVENTORY_REDFISH / INVENTORY_IPMI / HC / PXE) —
# allocation state, not identity
# ---------------------------------------------------------------------------
def _get_segment(cidr):
    return requests.get(f"{API}/segments/by-segment", params={"segment": cidr},
                        timeout=TIMEOUT).json()


def _allocate(cluster, seg_type, site="site1"):
    return requests.post(f"{API}/segments/allocate",
                         json={"cluster_name": cluster, "site": site, "type": seg_type},
                         headers=AUTH_HEADERS, timeout=TIMEOUT)


class TestSegmentType:
    def test_new_segment_has_no_type(self, segment_factory):
        # A segment is not born as any kind: the type is stamped on when it
        # is allocated. (It used to be set at creation, defaulting to HC.)
        v = next_vlan()
        cidr = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr)
        assert r.status_code == 200, r.text
        got = _get_segment(cidr)
        assert got["status"] == "Available"
        assert got["type"] is None

    def test_type_on_create_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(type="HC", site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        assert r.status_code == 422  # extra="forbid"

    @pytest.mark.parametrize(
        "seg_type",
        ["MCE", "INVENTORY_REDFISH", "INVENTORY_IPMI", "HC", "PXE"],
    )
    def test_allocation_stamps_the_type_and_release_clears_it(
        self, segment_factory, release_allocated, seg_type
    ):
        v = next_vlan()
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                               segment=cidr_for("site1", v)).status_code == 200

        a = _allocate(f"it-type-{uuid.uuid4().hex[:6]}", seg_type)
        assert a.status_code == 200, a.text
        allocated = a.json()["segment"]
        release_allocated(allocated)
        assert a.json()["type"] == seg_type
        assert _get_segment(allocated)["type"] == seg_type

        rel = requests.post(f"{API}/segments/release", json={"segment": allocated},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert rel.status_code == 200, rel.text
        got = _get_segment(allocated)
        assert got["status"] == "Available"
        assert got["type"] is None

    def test_any_available_segment_serves_any_type(self, segment_factory, release_allocated):
        # The pool is shared: one Available segment can be allocated as HC
        # and, once released, as PXE — nothing about it was ever HC-only.
        v = next_vlan()
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                               segment=cidr_for("site1", v)).status_code == 200

        for seg_type in ("HC", "PXE"):
            a = _allocate(f"it-pool-{uuid.uuid4().hex[:6]}", seg_type)
            assert a.status_code == 200, a.text
            release_allocated(a.json()["segment"])
            assert a.json()["type"] == seg_type
            requests.post(f"{API}/segments/release", json={"segment": a.json()["segment"]},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)

    def test_allocate_invalid_type_rejected(self):
        r = _allocate("it-bogus-type", "BOGUS")
        assert r.status_code == 422

    def test_allocate_without_type_rejected(self):
        r = requests.post(f"{API}/segments/allocate",
                          json={"cluster_name": "it-no-type", "site": "site1"},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 422

    def test_get_segments_filters_by_allocated_type(self, segment_factory, release_allocated):
        v = next_vlan()
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                               segment=cidr_for("site1", v)).status_code == 200
        a = _allocate(f"it-filter-{uuid.uuid4().hex[:6]}", "PXE")
        assert a.status_code == 200, a.text
        allocated = a.json()["segment"]
        release_allocated(allocated)

        matching = requests.get(f"{API}/segments", params={"site": "site1", "type": "PXE"},
                                timeout=TIMEOUT)
        assert matching.status_code == 200
        assert any(s["segment"] == allocated for s in matching.json())

        non_matching = requests.get(f"{API}/segments", params={"site": "site1", "type": "HC"},
                                    timeout=TIMEOUT)
        assert not any(s["segment"] == allocated for s in non_matching.json())


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class TestSegmentCRUD:
    def test_new_segment_is_available(self, segment_factory):
        # A segment is born Available — immediately allocatable, with no
        # unlock step. (Segments used to be created "Locked" and stay excluded
        # from allocation until the firewall workflow unlocked them.)
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200, r.text

        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["status"] == "Available"

    def test_create_get_list_delete(self, segment_factory):
        v = next_vlan()
        epg = _uid()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=epg, segment=seg)
        assert r.status_code == 200, r.text

        # get by CIDR (the natural key) — and no vrf field
        g = requests.get(f"{API}/segments/by-segment", params={"segment": seg}, timeout=TIMEOUT)
        assert g.status_code == 200
        doc = g.json()
        assert doc["vlan_id"] == v and doc["epg_name"] == epg
        assert "vrf" not in doc

        # appears in list, still no vrf field
        lst = requests.get(f"{API}/segments?site=site1", timeout=TIMEOUT).json()
        assert any(s["epg_name"] == epg for s in lst)
        assert all("vrf" not in s for s in lst)

        # delete by CIDR, then it's gone
        d = requests.delete(f"{API}/segments", params={"segment": seg},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert d.status_code == 200
        gone = requests.get(f"{API}/segments/by-segment", params={"segment": seg}, timeout=TIMEOUT)
        assert gone.status_code == 404

    def test_update_dhcp(self, segment_factory):
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg, dhcp=False)
        assert r.status_code == 200

        u = requests.patch(f"{API}/segments", json={"segment": seg, "dhcp": True},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert u.status_code == 200, u.text
        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg}, timeout=TIMEOUT)
        assert got.json()["dhcp"] is True

        # idempotent: setting the same value again succeeds
        again = requests.patch(f"{API}/segments", json={"segment": seg, "dhcp": True},
                               headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert again.status_code == 200

    def test_update_only_dhcp_is_mutable(self, segment_factory):
        # dhcp is the only mutable field — anything else in the update body
        # is rejected (extra="forbid")
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200

        u = requests.patch(f"{API}/segments",
                           json={"segment": seg, "dhcp": True, "epg_name": _uid("UPD")},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert u.status_code == 422

    def test_update_clusters_by_segment(self, segment_factory):
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200

        # assigning a cluster allocates the segment, so it needs a type
        untyped = requests.put(f"{API}/segments/clusters",
                               json={"segment": seg, "cluster_name": "cluster-a"},
                               headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert untyped.status_code == 422, untyped.text

        u = requests.put(f"{API}/segments/clusters",
                         json={"segment": seg, "cluster_name": "cluster-a", "type": "MCE"},
                         headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert u.status_code == 200, u.text
        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["cluster_name"] == "cluster-a"
        assert got["type"] == "MCE"
        assert got["status"] == "Allocated"

        # a comma-separated list is no longer a valid cluster name — shared
        # segments were retired, one segment belongs to at most one cluster
        shared = requests.put(f"{API}/segments/clusters",
                              json={"segment": seg, "cluster_name": "shared-a,shared-b",
                                    "type": "MCE"},
                              headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert shared.status_code == 400, shared.text

        # releasing clears the type, so sending one with a release is refused
        typed_release = requests.put(f"{API}/segments/clusters",
                                     json={"segment": seg, "cluster_name": "", "type": "MCE"},
                                     headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert typed_release.status_code == 422, typed_release.text

        # empty cluster_name releases the segment (also makes teardown deletable)
        rel = requests.put(f"{API}/segments/clusters",
                           json={"segment": seg, "cluster_name": ""},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert rel.status_code == 200
        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["cluster_name"] is None
        assert got["type"] is None
        assert got["status"] == "Available"

    def test_get_unknown_segment_404(self):
        r = requests.get(f"{API}/segments/by-segment", params={"segment": "10.255.254.0/24"},
                         timeout=TIMEOUT)
        assert r.status_code == 404

    def test_object_id_routes_gone(self):
        # single-segment routes are keyed by CIDR now; the /segments/{id} path is gone
        assert requests.get(f"{API}/segments/deadbeefdeadbeefdeadbeef",
                            timeout=TIMEOUT).status_code == 404


# ---------------------------------------------------------------------------
# Per-site uniqueness (the core of the decentralized model)
# ---------------------------------------------------------------------------
class TestPerSiteUniqueness:
    def test_duplicate_vlan_same_site_rejected(self, segment_factory):
        v = next_vlan()
        r1 = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v))
        assert r1.status_code == 200
        # same VLAN, same site, different CIDR -> rejected
        v2 = next_vlan()
        r2 = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v2))
        assert r2.status_code == 400

    def test_same_vlan_different_site_allowed(self, segment_factory):
        v = next_vlan()
        r1 = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v))
        assert r1.status_code == 200
        r2 = segment_factory(site="site2", vlan_id=v, epg_name=_uid(), segment=cidr_for("site2", v))
        assert r2.status_code == 200

    def test_epg_reuse_with_different_vlan_same_site_rejected(self, segment_factory):
        epg = _uid()
        v1, v2 = next_vlan(), next_vlan()
        r1 = segment_factory(site="site1", vlan_id=v1, epg_name=epg, segment=cidr_for("site1", v1))
        assert r1.status_code == 200
        r2 = segment_factory(site="site1", vlan_id=v2, epg_name=epg, segment=cidr_for("site1", v2))
        assert r2.status_code == 400


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
class TestAllocation:
    def test_allocate_idempotent_release(self, segment_factory, release_allocated):
        # Seed an available segment at site1
        v = next_vlan()
        seg = cidr_for("site1", v)
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg).status_code == 200

        cluster = f"it-cluster-{uuid.uuid4().hex[:6]}"

        a1 = requests.post(f"{API}/segments/allocate",
                           json={"cluster_name": cluster, "site": "site1", "type": "HC"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a1.status_code == 200, a1.text
        data = a1.json()
        release_allocated(data["segment"])
        assert "vlan_id" in data
        assert data["type"] == "HC"
        assert "vrf" not in data

        # idempotent: re-allocating the same cluster returns the same VLAN
        a2 = requests.post(f"{API}/segments/allocate",
                           json={"cluster_name": cluster, "site": "site1", "type": "HC"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a2.status_code == 200
        assert a2.json()["vlan_id"] == data["vlan_id"]

        # release is keyed by the CIDR alone
        rel = requests.post(f"{API}/segments/release",
                            json={"segment": data["segment"]},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert rel.status_code == 200
        assert "released" in rel.text.lower()

        got = requests.get(f"{API}/segments/by-segment",
                           params={"segment": data["segment"]}, timeout=TIMEOUT).json()
        assert got["status"] == "Available"
        assert got["cluster_name"] is None

    def test_release_unknown_segment_404(self):
        r = requests.post(f"{API}/segments/release",
                          json={"segment": "10.255.253.0/24"},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404

    def test_release_is_idempotent(self, segment_factory):
        # Releasing an already-Available segment is a no-op, not an error
        v = next_vlan()
        seg = cidr_for("site1", v)
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg).status_code == 200

        for _ in range(2):
            r = requests.post(f"{API}/segments/release", json={"segment": seg},
                              headers=AUTH_HEADERS, timeout=TIMEOUT)
            assert r.status_code == 200, r.text

        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["status"] == "Available"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_shape(self):
        """GET /api/stats is trimmed to {site, total_segments, allocated, by_type} for the UI site cards.

        by_type holds plain allocated COUNTS per type — no per-type total, since
        an Available segment has no type. Every type is listed, and together
        they account for every allocation. Site-level utilization is still
        computed by get_all_sites_statistics() but is only exposed via /api/health.
        """
        r = requests.get(f"{API}/stats", timeout=TIMEOUT)
        assert r.status_code == 200
        stats = r.json()
        assert isinstance(stats, list) and len(stats) > 0
        for s in stats:
            assert set(s) == {"site", "total_segments", "allocated", "by_type"}
            assert 0 <= s["allocated"] <= s["total_segments"]
            assert [t["type"] for t in s["by_type"]] == [
                "HC", "MCE", "INVENTORY_REDFISH", "INVENTORY_IPMI", "PXE"
            ]
            for entry in s["by_type"]:
                assert set(entry) == {"type", "allocated"}
            assert sum(t["allocated"] for t in s["by_type"]) == s["allocated"]

    def test_stats_count_an_allocation(self, segment_factory, release_allocated):
        def site1():
            stats = requests.get(f"{API}/stats", timeout=TIMEOUT).json()
            return next(s for s in stats if s["site"] == "site1")

        v = next_vlan()
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                               segment=cidr_for("site1", v)).status_code == 200
        def by_type(stat):
            return {t["type"]: t["allocated"] for t in stat["by_type"]}

        before = site1()
        a = _allocate(f"it-stats-{uuid.uuid4().hex[:6]}", "PXE")
        assert a.status_code == 200, a.text
        release_allocated(a.json()["segment"])
        after = site1()
        assert after["allocated"] == before["allocated"] + 1
        assert after["total_segments"] == before["total_segments"]
        assert by_type(after)["PXE"] == by_type(before)["PXE"] + 1
        assert by_type(after)["HC"] == by_type(before)["HC"]

    def test_health_exposes_site_totals(self):
        r = requests.get(f"{API}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        summary = r.json()["sites_summary"]
        for site_stats in summary.values():
            for key in ("total", "allocated", "available", "utilization"):
                assert key in site_stats


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
