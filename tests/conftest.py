"""Shared pytest fixtures for Segments Manager integration tests.

These tests run against a LIVE server (local `python main.py` or the
container image). Configure the target with environment variables:

    SEGMENTS_MANAGER_URL   base URL (default: http://127.0.0.1:8000)
    VLAN_AUTH_USER     basic-auth user (default: admin)
    VLAN_AUTH_PASS     basic-auth pass (default: admin)

The suite assumes the server is configured with:
    SITES=site1,site2,site3
    SITE_PREFIXES=site1:192,site2:193,site3:194
"""

import os
import random
import itertools

import pytest
import requests

BASE_URL = os.getenv("SEGMENTS_MANAGER_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE_URL}/api"
AUTH = (os.getenv("VLAN_AUTH_USER", "admin"), os.getenv("VLAN_AUTH_PASS", "admin"))
TIMEOUT = 15

# First IP octet per site (must match the server's SITE_PREFIXES config).
SITE_OCTET = {"site1": "192", "site2": "193", "site3": "194"}

# Randomized, monotonic VLAN IDs in a high band to avoid colliding with
# any real data. Each id maps 1:1 to a unique CIDR (see cidr_for).
_vlan_counter = itertools.count(random.randint(3000, 3800))


def next_vlan() -> int:
    """Return a fresh VLAN ID unique to this test session."""
    return next(_vlan_counter)


def cidr_for(site: str, vlan: int) -> str:
    """Deterministic, globally-unique CIDR that matches the site's IP prefix."""
    return f"{SITE_OCTET[site]}.{vlan // 256}.{vlan % 256}.0/24"


@pytest.fixture(scope="session", autouse=True)
def _require_server():
    """Skip the whole suite if the server is not reachable/healthy."""
    try:
        r = requests.get(f"{API}/health", timeout=TIMEOUT)
    except requests.RequestException as e:
        pytest.skip(f"Segments Manager not reachable at {BASE_URL}: {e}")
        return
    if r.status_code != 200:
        pytest.skip(f"Segments Manager health check returned {r.status_code}")


@pytest.fixture
def api():
    return API


@pytest.fixture
def auth():
    return AUTH


@pytest.fixture
def segment_factory():
    """Create segments and auto-delete them after the test.

    Usage:
        r = segment_factory(site="site1", vlan_id=..., epg_name=..., segment=...)
    Returns the raw `requests.Response`. Any segment that was successfully
    created (HTTP 200 with an id) is deleted during teardown.

    New segments start locked (excluded from auto-allocation) by default, so
    this factory unlocks them right after creation unless `keep_locked=True`
    is passed — most tests expect an immediately-allocatable segment.
    """
    created_ids = []

    def _create(**body):
        keep_locked = body.pop("keep_locked", False)
        body.setdefault("dhcp", False)
        r = requests.post(f"{API}/segments", json=body, auth=AUTH, timeout=TIMEOUT)
        if r.status_code == 200 and "id" in r.json():
            sid = r.json()["id"]
            created_ids.append(sid)
            if not keep_locked:
                requests.post(
                    f"{API}/segments/{sid}/unlock",
                    auth=AUTH,
                    timeout=TIMEOUT,
                )
        return r

    yield _create

    for sid in created_ids:
        try:
            requests.delete(f"{API}/segments/{sid}", auth=AUTH, timeout=TIMEOUT)
        except requests.RequestException:
            pass


@pytest.fixture
def release_cluster():
    """Ensure clusters allocated during a test are released afterwards."""
    allocated = []

    def _track(cluster_name, site):
        allocated.append((cluster_name, site))

    yield _track

    for cluster_name, site in allocated:
        try:
            requests.post(
                f"{API}/release-vlan",
                json={"cluster_name": cluster_name, "site": site},
                auth=AUTH,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            pass
