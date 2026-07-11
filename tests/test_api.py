"""Segments Manager — MongoDB integration test suite.

Runs against a live server. See conftest.py for configuration.

Covers the decentralized, per-site MongoDB model:
  * no VRF anywhere (legacy `vrf` field is rejected)
  * VLAN IDs and EPG names are unique PER SITE
  * site IP-prefix enforcement, CIDR/subnet validation
  * atomic allocate / idempotent re-allocate / release
  * auth enforcement on write endpoints
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
        assert requests.delete(f"{API}/segments/deadbeefdeadbeefdeadbeef", timeout=TIMEOUT).status_code == 401


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
            r = segment_factory(type=t, site="site1", vlan_id=v, epg_name=_uid(),
                                segment=cidr_for("site1", v))
            assert r.status_code == 200, r.text
            got = requests.get(f"{API}/segments/{r.json()['id']}", timeout=TIMEOUT)
            assert got.json()["type"] == t

    def test_invalid_type_rejected(self, segment_factory):
        v = next_vlan()
        r = segment_factory(type="BOGUS", site="site1", vlan_id=v, epg_name=_uid(),
                            segment=cidr_for("site1", v))
        assert r.status_code == 422

    def test_missing_type_defaults_to_hc(self):
        v = next_vlan()
        body = {"site": "site1", "vlan_id": v, "epg_name": _uid(),
                "segment": cidr_for("site1", v), "dhcp": False}
        r = requests.post(f"{API}/segments", json=body, headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        got = requests.get(f"{API}/segments/{r.json()['id']}", timeout=TIMEOUT)
        assert got.json()["type"] == "HC"

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
        sid = r.json()["id"]

        # get by id — and no vrf field
        g = requests.get(f"{API}/segments/{sid}", timeout=TIMEOUT)
        assert g.status_code == 200
        doc = g.json()
        assert doc["vlan_id"] == v and doc["epg_name"] == epg
        assert "vrf" not in doc

        # appears in list, still no vrf field
        lst = requests.get(f"{API}/segments?site=site1", timeout=TIMEOUT).json()
        assert any(s["epg_name"] == epg for s in lst)
        assert all("vrf" not in s for s in lst)

        # delete
        d = requests.delete(f"{API}/segments/{sid}", headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert d.status_code == 200

    def test_update_segment(self, segment_factory):
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200
        sid = r.json()["id"]

        new_epg = _uid("UPD")
        body = {"type": "MCE", "site": "site1", "vlan_id": v, "epg_name": new_epg,
                "segment": seg, "dhcp": True}
        u = requests.put(f"{API}/segments/{sid}", json=body, headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert u.status_code == 200, u.text
        assert requests.get(f"{API}/segments/{sid}", timeout=TIMEOUT).json()["epg_name"] == new_epg

    def test_bad_object_id(self):
        assert requests.get(f"{API}/segments/not-an-objectid", timeout=TIMEOUT).status_code == 400


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
# Locking (segments start locked; excluded from auto-allocation until unlocked)
# ---------------------------------------------------------------------------
class TestSegmentLocking:
    def test_new_segment_defaults_locked(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v),
                            keep_locked=True)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]

        got = requests.get(f"{API}/segments/{sid}", timeout=TIMEOUT)
        assert got.status_code == 200
        assert got.json()["locked"] is True

    def test_locked_segment_excluded_from_allocation(self, segment_factory, release_cluster):
        # Create one locked segment and confirm the atomic allocator never
        # hands it out — it skips straight past to an unlocked candidate.
        v = next_vlan()
        r = segment_factory(site="site3", vlan_id=v, epg_name=_uid(), segment=cidr_for("site3", v),
                            keep_locked=True)
        assert r.status_code == 200, r.text
        locked_segment_value = cidr_for("site3", v)

        cluster = f"it-locktest-{uuid.uuid4().hex[:6]}"
        release_cluster(cluster, "site3")

        a1 = requests.post(f"{API}/allocate-segment",
                           json={"cluster_name": cluster, "site": "site3"},
                           headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert a1.status_code == 200, a1.text
        assert a1.json()["segment"] != locked_segment_value

    def test_unlock_makes_segment_allocatable(self, segment_factory, release_cluster):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v),
                            keep_locked=True)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]

        unlock = requests.post(f"{API}/segments/{sid}/unlock", headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert unlock.status_code == 200, unlock.text

        got = requests.get(f"{API}/segments/{sid}", timeout=TIMEOUT)
        assert got.json()["locked"] is False

        cluster = f"it-unlocktest-{uuid.uuid4().hex[:6]}"
        release_cluster(cluster, "site1")
        alloc = requests.post(f"{API}/allocate-segment",
                              json={"cluster_name": cluster, "site": "site1"},
                              headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert alloc.status_code == 200, alloc.text

    def test_unlock_idempotent(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site2", vlan_id=v, epg_name=_uid(), segment=cidr_for("site2", v),
                            keep_locked=True)
        sid = r.json()["id"]

        first = requests.post(f"{API}/segments/{sid}/unlock", headers=AUTH_HEADERS, timeout=TIMEOUT)
        second = requests.post(f"{API}/segments/{sid}/unlock", headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert first.status_code == 200
        assert second.status_code == 200

    def test_unlock_requires_auth(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v),
                            keep_locked=True)
        sid = r.json()["id"]

        unauth = requests.post(f"{API}/segments/{sid}/unlock", timeout=TIMEOUT)
        assert unauth.status_code == 401

    def test_no_relock_endpoint_exists(self, segment_factory):
        # Segment lifecycle is one-way: locked -> available -> allocated -> available.
        # There must be no API surface that can set locked back to True.
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v))
        sid = r.json()["id"]

        old_lock_route = requests.put(f"{API}/segments/{sid}/lock", json={"locked": True},
                                      headers=AUTH_HEADERS, timeout=TIMEOUT)
        assert old_lock_route.status_code == 404

        # The general segment-update endpoint must not be able to re-lock either.
        seg = requests.get(f"{API}/segments/{sid}", timeout=TIMEOUT).json()
        update = requests.put(f"{API}/segments/{sid}", headers=AUTH_HEADERS, timeout=TIMEOUT, json={
            "type": seg.get("type", "MCE"), "site": seg["site"], "vlan_id": seg["vlan_id"],
            "epg_name": seg["epg_name"], "segment": seg["segment"], "dhcp": seg["dhcp"],
            "locked": True,
        })
        assert update.status_code in (400, 422)

    def test_get_segments_filters_by_locked(self, segment_factory):
        v = next_vlan()
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=cidr_for("site1", v),
                            keep_locked=True)
        sid = r.json()["id"]

        locked_only = requests.get(f"{API}/segments", params={"site": "site1", "locked": "true"},
                                   timeout=TIMEOUT)
        assert locked_only.status_code == 200
        assert any(s["_id"] == sid for s in locked_only.json())

        unlocked_only = requests.get(f"{API}/segments", params={"site": "site1", "locked": "false"},
                                     timeout=TIMEOUT)
        assert not any(s["_id"] == sid for s in unlocked_only.json())


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
        for key in ("site", "total_segments", "allocated", "available", "utilization"):
            assert key in s


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
