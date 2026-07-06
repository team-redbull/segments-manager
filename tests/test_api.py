"""VLAN Manager — MongoDB integration test suite.

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

from conftest import API, AUTH, TIMEOUT, next_vlan, cidr_for


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
        body = {"site": "site1", "vlan_id": v, "epg_name": _uid(),
                "segment": cidr_for("site1", v), "dhcp": False}
        assert requests.post(f"{API}/segments", json=body, timeout=TIMEOUT).status_code == 401

    def test_allocate_requires_auth(self):
        body = {"cluster_name": "noauth-cluster", "site": "site1"}
        assert requests.post(f"{API}/allocate-vlan", json=body, timeout=TIMEOUT).status_code == 401

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
# CRUD
# ---------------------------------------------------------------------------
class TestSegmentCRUD:
    def test_create_get_list_delete(self, segment_factory):
        v = next_vlan()
        epg = _uid()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=epg, segment=seg,
                            description="crud test")
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
        d = requests.delete(f"{API}/segments/{sid}", auth=AUTH, timeout=TIMEOUT)
        assert d.status_code == 200

    def test_update_segment(self, segment_factory):
        v = next_vlan()
        seg = cidr_for("site1", v)
        r = segment_factory(site="site1", vlan_id=v, epg_name=_uid(), segment=seg)
        assert r.status_code == 200
        sid = r.json()["id"]

        new_epg = _uid("UPD")
        body = {"site": "site1", "vlan_id": v, "epg_name": new_epg,
                "segment": seg, "dhcp": True, "description": "updated"}
        u = requests.put(f"{API}/segments/{sid}", json=body, auth=AUTH, timeout=TIMEOUT)
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

        a1 = requests.post(f"{API}/allocate-vlan",
                           json={"cluster_name": cluster, "site": "site1"},
                           auth=AUTH, timeout=TIMEOUT)
        assert a1.status_code == 200, a1.text
        data = a1.json()
        assert "vlan_id" in data
        assert "vrf" not in data

        # idempotent: re-allocating the same cluster returns the same VLAN
        a2 = requests.post(f"{API}/allocate-vlan",
                           json={"cluster_name": cluster, "site": "site1"},
                           auth=AUTH, timeout=TIMEOUT)
        assert a2.status_code == 200
        assert a2.json()["vlan_id"] == data["vlan_id"]

        # release
        rel = requests.post(f"{API}/release-vlan",
                            json={"cluster_name": cluster, "site": "site1"},
                            auth=AUTH, timeout=TIMEOUT)
        assert rel.status_code == 200
        assert "released" in rel.text.lower()

    def test_release_unknown_cluster_404(self):
        r = requests.post(f"{API}/release-vlan",
                          json={"cluster_name": f"nope-{uuid.uuid4().hex[:6]}", "site": "site1"},
                          auth=AUTH, timeout=TIMEOUT)
        assert r.status_code == 404


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
