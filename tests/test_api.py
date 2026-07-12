"""Segments Manager — MongoDB integration test suite.

Runs against a live server. See conftest.py for configuration.

Covers the decentralized, per-site MongoDB model:
  * no VRF anywhere (legacy `vrf` field is rejected)
  * VLAN IDs and EPG names are unique PER SITE
  * site IP-prefix enforcement, CIDR/subnet validation
  * atomic allocate / idempotent re-allocate / release
  * auth enforcement on write endpoints
  * single-segment operations keyed by the segment CIDR (the natural key —
    unique + immutable); the ObjectId-based /segments/{id} routes are gone
"""

import uuid

import requests

from conftest import API, AUTH_HEADERS, TIMEOUT, next_vlan, cidr_for


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


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class TestAuthRequired:
    def test_create_requires_auth(self):
        v = next_vlan()
        body = {"type": "MCE", "site": "site1", "vlan_id": v, "epg_name": _uid(),
                "segment": cidr_for("site1", v), "dhcp": False}
        assert requests.post(f"{API}/segments", json=body, timeout=TIMEOUT).status_code == 401

    def test_allocate_requires_auth(self):
        body = {"cluster_name": "noauth-cluster", "site": "site1"}
        assert requests.post(f"{API}/allocate-segment", json=body, timeout=TIMEOUT).status_code == 401

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
                            segment="192.50.50.0/24")
        assert r.status_code == 422

    def test_invalid_site(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="does-not-exist", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        assert r.status_code in (400, 422)

    def test_wrong_ip_prefix_for_site(self, segment_factory):
        v = next_vlan()
        # site1 expects 192.x; give it a 193.x (site2's prefix)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site2", v))
        assert r.status_code == 400

    def test_non_network_address_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="192.168.1.5/24")  # host address, not network
        assert r.status_code == 400

    def test_missing_mask_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(),
                            segment="192.168.1.0")  # no /mask
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Segment type (MCE / INVENTORY / HC / PXE)
# ---------------------------------------------------------------------------
class TestSegmentType:
    def test_each_valid_type_accepted(self, segment_factory):
        for t in ("MCE", "INVENTORY", "HC", "PXE"):
            v = next_vlan()
            cidr = cidr_for("site1", v)
            r = segment_factory(type=t, site="site1", vlan_id=v, epg_name=_uid(),
                                segment=cidr)
            assert r.status_code == 200, r.text
            got = requests.get(f"{API}/segments/by-segment", params={"segment": cidr},
                               timeout=TIMEOUT)
            assert got.json()["type"] == t

    def test_invalid_type_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(type="BOGUS", site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        assert r.status_code == 422

    def test_missing_type_defaults_to_hc(self):
        v = next_vlan()
        cidr = cidr_for("site1", v)
        body = {"site": "site1", "vlan_id": v, "epg_name": _uid(),
                "segment": cidr, "dhcp": False}
        r = requests.post(f"{API}/segments", json=body, headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        try:
            got = requests.get(f"{API}/segments/by-segment", params={"segment": cidr},
                               timeout=TIMEOUT)
            assert got.json()["type"] == "HC"
        finally:
            requests.delete(f"{API}/segments", params={"segment": cidr},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)

    def test_get_segments_filters_by_type(self, segment_factory):
        v = next_vlan()
        r = segment_factory(type="PXE", site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        sid = r.json()["id"]

        matching = requests.get(f"{API}/segments", params={"site": "site1", "type": "PXE"},
                                timeout=TIMEOUT)
        assert matching.status_code == 200
        assert any(s["_id"] == sid for s in matching.json())

        non_matching = requests.get(f"{API}/segments", params={"site": "site1", "type": "HC"},
                                    timeout=TIMEOUT)
        assert not any(s["_id"] == sid for s in non_matching.json())


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
class TestSegmentCRUD:
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

        u = requests.put(f"{API}/segments/clusters",
                         json={"segment": seg, "cluster_names": "shared-a,shared-b"},
                         headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert u.status_code == 200, u.text
        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["cluster_name"] == "shared-a,shared-b"

        # empty cluster_names releases the segment (also makes teardown deletable)
        rel = requests.put(f"{API}/segments/clusters",
                           json={"segment": seg, "cluster_names": ""},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert rel.status_code == 200
        got = requests.get(f"{API}/segments/by-segment", params={"segment": seg},
                           timeout=TIMEOUT).json()
        assert got["cluster_name"] is None

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
    def test_allocate_idempotent_release(self, segment_factory, release_cluster):
        # Seed an available segment at site1
        v = next_vlan()
        seg = cidr_for("site1", v)
        assert segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg).status_code == 200

        cluster = f"it-cluster-{uuid.uuid4().hex[:6]}"
        release_cluster(cluster, "site1")

        a1 = requests.post(f"{API}/allocate-segment",
                           json={"cluster_name": cluster, "site": "site1"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a1.status_code == 200, a1.text
        data = a1.json()
        assert "vlan_id" in data
        assert "vrf" not in data

        # idempotent: re-allocating the same cluster returns the same VLAN
        a2 = requests.post(f"{API}/allocate-segment",
                           json={"cluster_name": cluster, "site": "site1"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a2.status_code == 200
        assert a2.json()["vlan_id"] == data["vlan_id"]

        # release
        rel = requests.post(f"{API}/release-segment",
                            json={"cluster_name": cluster, "site": "site1"},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert rel.status_code == 200
        assert "released" in rel.text.lower()

    def test_release_unknown_cluster_404(self):
        r = requests.post(f"{API}/release-segment",
                          json={"cluster_name": f"nope-{uuid.uuid4().hex[:6]}", "site": "site1"},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Lifecycle status (segments start "Locked"; excluded from auto-allocation
# until unlocked to "Available"; allocation sets "Allocated")
# ---------------------------------------------------------------------------
class TestSegmentLocking:
    def test_new_segment_defaults_locked(self, segment_factory):
        v = next_vlan()
        cidr = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr,
                            keep_locked=True)
        assert r.status_code == 200, r.text

        got = requests.get(f"{API}/segments/by-segment", params={"segment": cidr}, timeout=TIMEOUT)
        assert got.status_code == 200
        assert got.json()["status"] == "Locked"
        assert "locked" not in got.json()  # legacy boolean is gone

    def test_locked_segment_excluded_from_allocation(self, segment_factory, release_cluster):
        # Create one locked segment and confirm the atomic allocator never
        # hands it out — it skips straight past to an unlocked candidate
        # (provisioned here too, so the test is self-sufficient on an empty DB).
        v = next_vlan()
        r = segment_factory(site="site3", vlan_id=v, epg_name=_uid(), segment=cidr_for("site3", v),
                            keep_locked=True)
        assert r.status_code == 200, r.text
        locked_segment_value = cidr_for("site3", v)

        v_available = next_vlan()
        r2 = segment_factory(site="site3", vlan_id=v_available, epg_name=_uid(),
                             segment=cidr_for("site3", v_available))
        assert r2.status_code == 200, r2.text

        cluster = f"it-locktest-{uuid.uuid4().hex[:6]}"
        release_cluster(cluster, "site3")

        a1 = requests.post(f"{API}/allocate-segment",
                           json={"cluster_name": cluster, "site": "site3"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a1.status_code == 200, a1.text
        assert a1.json()["segment"] != locked_segment_value

    def test_unlock_makes_segment_allocatable(self, segment_factory, release_cluster):
        v = next_vlan()
        cidr = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr,
                            keep_locked=True)
        assert r.status_code == 200, r.text

        unlock = requests.post(f"{API}/segments/unlock", json={"segment": cidr},
                               headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert unlock.status_code == 200, unlock.text

        got = requests.get(f"{API}/segments/by-segment", params={"segment": cidr}, timeout=TIMEOUT)
        assert got.json()["status"] == "Available"

        cluster = f"it-unlocktest-{uuid.uuid4().hex[:6]}"
        release_cluster(cluster, "site1")
        alloc = requests.post(f"{API}/allocate-segment",
                              json={"cluster_name": cluster, "site": "site1"},
                              headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert alloc.status_code == 200, alloc.text

    def test_no_relock_endpoint_exists(self, segment_factory):
        # Segment lifecycle is one-way: Locked -> Available -> Allocated -> Available.
        # There must be no API surface that can set status back to "Locked".
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200

        old_lock_route = requests.put(f"{API}/segments/deadbeefdeadbeefdeadbeef/lock",
                                      json={"status": "Locked"},
                                      headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert old_lock_route.status_code == 404

        # The dhcp-update endpoint must not be able to re-lock either
        # (status is server-managed; the request model forbids extra fields).
        update = requests.patch(f"{API}/segments", headers=AUTH_HEADERS, timeout=TIMEOUT,
                                json={"segment": seg, "dhcp": True, "status": "Locked"})
        assert update.status_code in (400, 422)

    def test_get_segments_filters_by_status(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v),
                            keep_locked=True)
        sid = r.json()["id"]

        locked_only = requests.get(f"{API}/segments", params={"site": "site1", "status": "Locked"},
                                   timeout=TIMEOUT)
        assert locked_only.status_code == 200
        assert any(s["_id"] == sid for s in locked_only.json())

        available_only = requests.get(f"{API}/segments", params={"site": "site1", "status": "Available"},
                                      timeout=TIMEOUT)
        assert not any(s["_id"] == sid for s in available_only.json())


# ---------------------------------------------------------------------------
# Unlock by segment CIDR (natural key; used by the connectivity orchestrator)
# ---------------------------------------------------------------------------
class TestUnlockBySegment:
    def test_unlock_by_segment_value(self, segment_factory):
        v = next_vlan()
        cidr = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr,
                            keep_locked=True)
        assert r.status_code == 200, r.text

        unlock = requests.post(f"{API}/segments/unlock", json={"segment": cidr},
                               headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert unlock.status_code == 200, unlock.text

        got = requests.get(f"{API}/segments/by-segment", params={"segment": cidr}, timeout=TIMEOUT)
        assert got.json()["status"] == "Available"

    def test_unlock_by_segment_idempotent(self, segment_factory):
        v = next_vlan()
        cidr = cidr_for("site2", v)
        segment_factory(site="site2", vlan_id=v, epg_name=_uid(), segment=cidr,
                        keep_locked=True)

        first = requests.post(f"{API}/segments/unlock", json={"segment": cidr},
                              headers=AUTH_HEADERS, timeout=TIMEOUT)
        second = requests.post(f"{API}/segments/unlock", json={"segment": cidr},
                               headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert first.status_code == 200
        assert second.status_code == 200
        assert "already" in second.text.lower()

    def test_unlock_by_segment_unknown_404(self):
        r = requests.post(f"{API}/segments/unlock", json={"segment": "10.255.255.0/24"},
                          headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 404

    def test_unlock_by_segment_requires_auth(self, segment_factory):
        v = next_vlan()
        cidr = cidr_for("site1", v)
        segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr,
                        keep_locked=True)

        unauth = requests.post(f"{API}/segments/unlock", json={"segment": cidr}, timeout=TIMEOUT)
        assert unauth.status_code == 401


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_shape(self):
        r = requests.get(f"{API}/stats", timeout=TIMEOUT)
        assert r.status_code == 200
        stats = r.json()
        assert isinstance(stats, list) and len(stats) > 0
        s = stats[0]
        for key in ("site", "total_segments", "allocated", "available", "locked", "utilization"):
            assert key in s


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
