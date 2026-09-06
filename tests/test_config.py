"""Startup configuration tests for SITE_NETWORKS.

Unlike the rest of tests/, these need no running server — they are the only way
to cover "the server refuses to start", which the live-server suite structurally
cannot express.

Each case runs validate_site_networks() in a fresh subprocess, because
src/config/settings.py reads the environment once at import time. `env=` is
passed explicitly rather than merged with os.environ, and BOTH site variables are
always set (empty when the case wants them absent) — settings.py calls
load_dotenv(), which resolves .env relative to its own file rather than the cwd,
so the repo's .env cannot be escaped by changing directory. It can only be
pre-empted, since load_dotenv never overrides a variable already in the
environment, and an empty string counts as already set.
"""

import os
import sys
import json
import subprocess

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VALID = {
    "site1": {"pool": "192.10.0.0/16",
              "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"},
    "site2": {"pool": "193.51.0.0/16",
              "dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"},
}

_SCRIPT = (
    "import src.config.settings as s; "
    "s.validate_site_networks(); "
    "print('STARTED', s.SITES)"
)


def run_startup(site_networks=None, site_prefixes=None):
    """Import settings and validate under a controlled environment.

    Returns the CompletedProcess; returncode 0 means the app would have started.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "MONGODB_URL": "mongodb://localhost:27017",
        "API_TOKEN": "test-token",
        # Always set, so the repo's .env cannot supply either one.
        "SITE_NETWORKS": site_networks or "",
        "SITE_PREFIXES": site_prefixes or "",
    }

    return subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


def assert_refused(result, *expected_fragments):
    assert result.returncode != 0, f"expected startup to fail, got:\n{result.stdout}"
    for fragment in expected_fragments:
        assert fragment in result.stderr, (
            f"missing {fragment!r} in stderr:\n{result.stderr}"
        )


class TestValidConfig:

    def test_valid_config_starts(self):
        r = run_startup(json.dumps(VALID))
        assert r.returncode == 0, r.stderr
        assert "STARTED" in r.stdout

    def test_unknown_sub_key_is_tolerated(self):
        """The shared topology is rendered whole into both services' ConfigMaps,
        so a sub-key this service does not own must never break it."""
        cfg = {"site1": {"pool": "192.10.0.0/16", "dell-bmc": "10.50.0.0/16",
                         "cisco-bmc": "10.60.0.0/16", "future": 1}}
        r = run_startup(json.dumps(cfg))
        assert r.returncode == 0, r.stderr
        assert "unrecognised" in r.stderr

    def test_bmc_keys_are_optional(self):
        """This service owns `pool`. The vendor BMC keys are the
        segment-connectivity worker's, and it is the one that requires them."""
        r = run_startup(json.dumps({"site1": {"pool": "192.10.0.0/16"}}))
        assert r.returncode == 0, r.stderr

    def test_legacy_single_bmc_key_starts_but_is_flagged(self):
        """A ConfigMap still on the pre-vendor-split shape must not stop THIS
        service — it never reads the key. But it crash-loops the
        segment-connectivity worker, so say so in the log."""
        cfg = {"site1": {"pool": "192.10.0.0/16", "bmc": "10.50.0.0/16"}}
        r = run_startup(json.dumps(cfg))
        assert r.returncode == 0, r.stderr
        assert "unrecognised" in r.stderr
        assert "bmc" in r.stderr


class TestLegacyVar:

    def test_legacy_only_refuses_to_start(self):
        """New code against a stale ConfigMap: fail loudly rather than come up
        with no sites and reject every create while reporting Healthy."""
        r = run_startup(site_networks=None, site_prefixes="site1:192,site2:193")
        assert_refused(r, "SITE_PREFIXES is set but SITE_NETWORKS is not")

    def test_both_set_starts_with_warning(self):
        """The expand/contract rollout window — both keys present while images
        roll. This must NOT fail, or the migration has no safe ordering."""
        r = run_startup(json.dumps(VALID), site_prefixes="site1:192")
        assert r.returncode == 0, r.stderr
        assert "SITE_PREFIXES is set and IGNORED" in r.stderr

    def test_legacy_format_in_new_var_is_named(self):
        r = run_startup("site1:192,site2:193")
        assert_refused(r, "legacy SITE_PREFIXES format")


class TestInvalidConfig:

    def test_unset_refuses(self):
        assert_refused(run_startup(""), "SITE_NETWORKS is not set")

    def test_empty_object_refuses(self):
        assert_refused(run_startup("{}"), "non-empty JSON object")

    def test_missing_pool_names_the_site(self):
        cfg = {"site1": {"dell-bmc": "10.50.0.0/16"}}
        assert_refused(run_startup(json.dumps(cfg)), "site 'site1' has no \"pool\" key")

    @pytest.mark.parametrize("pool", ["192.10.0.1/16", "not-a-cidr", "192.10.0.0/33"])
    def test_bad_pool_cidr_refuses(self, pool):
        cfg = {"site1": {"pool": pool}}
        assert_refused(run_startup(json.dumps(cfg)), "invalid pool CIDR")

    def test_ipv6_pool_refuses(self):
        cfg = {"site1": {"pool": "2001:db8::/48"}}
        assert_refused(run_startup(json.dumps(cfg)), "must be IPv4")

    def test_overlapping_pools_refuse(self):
        cfg = {"site1": {"pool": "192.10.0.0/16"},
               "site2": {"pool": "192.10.5.0/24"}}
        assert_refused(run_startup(json.dumps(cfg)), "overlaps site 'site2' pool")

    @pytest.mark.parametrize("bmc_key", ["dell-bmc", "cisco-bmc"])
    def test_pool_overlapping_a_bmc_network_refuses(self, bmc_key):
        """The check that justifies the BMC keys living in this service's config
        at all: request validation can never catch it, because containment runs
        first. EVERY vendor's network is checked, not just the first."""
        cfg = {"site1": {"pool": "10.50.0.0/16"},
               "site2": {"pool": "193.51.0.0/16", bmc_key: "10.50.0.0/16"}}
        assert_refused(run_startup(json.dumps(cfg)), f"{bmc_key} BMC network")

    @pytest.mark.parametrize("bmc_key", ["dell-bmc", "cisco-bmc"])
    def test_bad_bmc_cidr_refuses(self, bmc_key):
        cfg = {"site1": {"pool": "192.10.0.0/16", bmc_key: "10.50.0.1/16"}}
        assert_refused(run_startup(json.dumps(cfg)), f"invalid {bmc_key} CIDR")

    def test_sites_differing_only_by_case_refuse(self):
        cfg = {"site1": {"pool": "192.10.0.0/16"},
               "Site1": {"pool": "193.51.0.0/16"}}
        assert_refused(run_startup(json.dumps(cfg)), "differ only by case")

    def test_site_mapping_to_a_scalar_refuses(self):
        assert_refused(run_startup('{"site1": "192.10.0.0/16"}'), "expected an object")
