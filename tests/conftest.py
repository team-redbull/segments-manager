"""Shared pytest fixtures for Segments Manager integration tests.

These tests run against a LIVE server (local `python main.py` or the
container image). Configure the target with environment variables:

    SEGMENTS_MANAGER_URL       base URL (default: http://127.0.0.1:8000)
    SEGMENTS_MANAGER_API_TOKEN  API token for write requests (must match the
                                server's API_TOKEN; falls back to $API_TOKEN,
                                then "test-token")

The suite assumes the server is configured with:
    SITE_NETWORKS={"site1": {"pool": "192.10.0.0/16",
                             "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"},
                   "site2": {"pool": "193.51.0.0/16",
                             "dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"},
                   "site3": {"pool": "194.52.0.0/16",
                             "dell-bmc": "10.52.0.0/16", "cisco-bmc": "10.62.0.0/16"}}
    API_TOKEN=test-token   (or match SEGMENTS_MANAGER_API_TOKEN)
"""

import os
import random
import ipaddress
import itertools

import pytest
import requests

BASE_URL = os.getenv("SEGMENTS_MANAGER_URL", "http://127.0.0.1:8000").rstrip("/")
API = f"{BASE_URL}/api"
API_TOKEN = os.getenv("SEGMENTS_MANAGER_API_TOKEN") or os.getenv("API_TOKEN", "test-token")
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}
TIMEOUT = 15

# Allocatable pool per site (must match the server's SITE_NETWORKS config).
SITE_POOL = {
    "site1": "192.10.0.0/16",
    "site2": "193.51.0.0/16",
    "site3": "194.52.0.0/16",
}

# Randomized, monotonic VLAN IDs in a high band to avoid colliding with
# any real data. Each id maps 1:1 to a unique CIDR (see cidr_for).
_vlan_counter = itertools.count(random.randint(3000, 3800))


def next_vlan() -> int:
    """Return a fresh VLAN ID unique to this test session."""
    return next(_vlan_counter)


def cidr_for(site: str, vlan: int) -> str:
    """Deterministic /24 carved out of the site's configured pool.

    A /16 pool holds exactly 256 /24s, so the VLAN maps onto the third octet.
    Two VLANs exactly 256 apart would collide, but next_vlan() hands out
    consecutive ids, so a session stays unique for its first 256 segments —
    well above what this suite creates.
    """
    pool = ipaddress.ip_network(SITE_POOL[site])
    return str(ipaddress.IPv4Network((int(pool.network_address) + (vlan % 256) * 256, 24)))


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
    return AUTH_HEADERS


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
    created_cidrs = []

    def _create(**body):
        keep_locked = body.pop("keep_locked", False)
        body.setdefault("dhcp", False)
        r = requests.post(f"{API}/segments", json=body, headers=AUTH_HEADERS, timeout=TIMEOUT)
        if r.status_code == 200 and "id" in r.json():
            cidr = body["segment"]
            created_cidrs.append(cidr)
            if not keep_locked:
                requests.post(
                    f"{API}/segments/unlock",
                    json={"segment": cidr},
                    headers=AUTH_HEADERS,
                    timeout=TIMEOUT,
                )
        return r

    yield _create

    for cidr in created_cidrs:
        try:
            requests.delete(f"{API}/segments", params={"segment": cidr},
                            headers=AUTH_HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            pass


@pytest.fixture
def release_allocated():
    """Release segments allocated during a test, so segment_factory can delete them.

    Release is keyed by the segment CIDR, so tests register the CIDR that the
    allocator actually handed back rather than the cluster they asked for —
    the allocator picks from the whole Available pool at a site, which is not
    necessarily the segment the test just created.
    """
    cidrs = []

    def _track(segment):
        cidrs.append(segment)

    yield _track

    for cidr in cidrs:
        try:
            requests.post(
                f"{API}/segments/release",
                json={"segment": cidr},
                headers=AUTH_HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            pass
