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

# Asserts the pool-exceptions rule at the parse layer, with no server and no
# HTTP: exact CIDR equality, and nothing else the listed range contains.
_EXACT_MATCH_SCRIPT = (
    "import ipaddress; import src.config.settings as s; "
    "s.validate_site_networks(); "
    "listed = s.SITE_POOL_EXCEPTIONS['site1']; "
    "assert listed == frozenset({ipaddress.ip_network('172.20.4.0/22')}), listed; "
    "assert ipaddress.ip_network('172.20.5.0/24') not in listed; "
    "assert ipaddress.ip_network('172.20.0.0/16') not in listed; "
    "assert s.get_site_pool_exceptions('SITE1') == listed; "
    "assert s.get_site_pool_exceptions('site2') == frozenset(); "
    "assert s.get_site_pool_exceptions('nope') == frozenset(); "
    "print('EXACT-MATCH-OK')"
)


def run_startup(site_networks=None, site_prefixes=None, script=_SCRIPT):
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
        [sys.executable, "-c", script],
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


# A /22 that clears every pool (192.10/193.51/194.52) and every BMC range
# (10.5x/10.6x), so it is exempt-able without tripping any startup check.
EXCEPTION = "172.20.4.0/22"


def _with_exceptions(*cidrs, site="site1"):
    """VALID, with `site` carrying the given pool-exceptions list."""
    cfg = {name: dict(net) for name, net in VALID.items()}
    cfg[site]["pool-exceptions"] = list(cidrs)
    return cfg


class TestPoolExceptions:
    """`pool-exceptions`: the per-site escape hatch for an out-of-pool network.

    The alternative it exists to avoid is widening the site's /16 pool, which
    loosens containment for every future segment in order to admit one legacy
    one. See NetworkValidators.validate_segment_format.
    """

    def test_valid_exception_starts(self):
        r = run_startup(json.dumps(_with_exceptions(EXCEPTION)))
        assert r.returncode == 0, r.stderr
        assert "STARTED" in r.stdout

    def test_the_key_is_not_reported_unrecognised(self):
        """This service OWNS the key. If it ever lands in the unknown-sub-key
        INFO log, the set in validate_site_networks has drifted."""
        r = run_startup(json.dumps(_with_exceptions(EXCEPTION)))
        assert r.returncode == 0, r.stderr
        assert "unrecognised" not in r.stderr

    def test_exceptions_are_named_in_the_startup_summary(self):
        """An out-of-pool segment is only creatable because of this list, so the
        startup log must say so without anyone opening the ConfigMap."""
        r = run_startup(json.dumps(_with_exceptions(EXCEPTION)))
        assert r.returncode == 0, r.stderr
        assert EXCEPTION in r.stderr
        assert "pool-exception" in r.stderr

    def test_exemption_is_exact_cidr_equality(self):
        """The rule that keeps one entry from opening the whole listed range:
        a listed /22 must not authorise the /24s inside it."""
        r = run_startup(json.dumps(_with_exceptions(EXCEPTION)),
                        script=_EXACT_MATCH_SCRIPT)
        assert r.returncode == 0, r.stderr
        assert "EXACT-MATCH-OK" in r.stdout

    def test_empty_list_is_a_no_op(self):
        r = run_startup(json.dumps(_with_exceptions()))
        assert r.returncode == 0, r.stderr

    def test_absent_key_is_a_no_op(self):
        """Regression guard: every site gets an entry in the exceptions map,
        so nothing downstream needs a default."""
        r = run_startup(json.dumps(VALID))
        assert r.returncode == 0, r.stderr
        assert "pool-exception" not in r.stderr


class TestInvalidPoolExceptions:
    """Every case here is a config that would otherwise be silently DEAD — the
    entry looks configured but no segment matching it could ever be created."""

    def test_non_list_refuses(self):
        cfg = dict(VALID)
        cfg["site1"] = dict(cfg["site1"], **{"pool-exceptions": EXCEPTION})
        assert_refused(run_startup(json.dumps(cfg)), "must be a JSON list")

    @pytest.mark.parametrize("cidr", ["172.20.4.1/22", "not-a-cidr", "172.20.4.0/33"])
    def test_bad_exception_cidr_refuses(self, cidr):
        assert_refused(run_startup(json.dumps(_with_exceptions(cidr))),
                       "invalid pool-exceptions[0] CIDR")

    def test_ipv6_exception_refuses(self):
        assert_refused(run_startup(json.dumps(_with_exceptions("2001:db8::/48"))),
                       "must be IPv4")

    @pytest.mark.parametrize("cidr", ["172.0.0.0/8", "172.20.4.1/32"])
    def test_exception_outside_the_supported_mask_range_refuses(self, cidr):
        """validate_subnet_mask would reject it forever — refuse it up front."""
        assert_refused(run_startup(json.dumps(_with_exceptions(cidr))),
                       "outside the supported /16-/31 range")

    @pytest.mark.parametrize("cidr", ["127.0.0.0/22", "169.254.0.0/22", "224.0.0.0/22"])
    def test_reserved_range_exception_refuses(self, cidr):
        """Same reasoning, for validate_no_reserved_ips."""
        assert_refused(run_startup(json.dumps(_with_exceptions(cidr))),
                       "the entry would be dead")

    def test_duplicate_exception_refuses(self):
        assert_refused(run_startup(json.dumps(_with_exceptions(EXCEPTION, EXCEPTION))),
                       "is listed twice")

    def test_exception_inside_its_own_pool_refuses(self):
        """Containment already admits it, so the entry exempts nothing. A
        silently redundant entry is how an operator comes to believe a range is
        exempted when the permission really came from a pool they later narrow."""
        assert_refused(run_startup(json.dumps(_with_exceptions("192.10.5.0/24"))),
                       "overlaps that site's own pool")

    def test_exception_overlapping_another_sites_pool_refuses(self):
        """validate_ip_overlap is global, so a segment created under this
        exemption would permanently block a range site2 legitimately owns."""
        assert_refused(run_startup(json.dumps(_with_exceptions("193.51.5.0/24"))),
                       "overlaps site 'site2' pool")

    @pytest.mark.parametrize("bmc_key", ["dell-bmc", "cisco-bmc"])
    def test_exception_overlapping_a_bmc_network_refuses(self, bmc_key):
        """The invariant this whole feature puts at risk. Containment used to
        guarantee no segment could reach a BMC network; an exception bypasses
        containment, so startup is the ONLY thing left that can catch it."""
        cfg = _with_exceptions("10.50.4.0/22")
        cfg["site2"][bmc_key] = "10.50.0.0/16"
        assert_refused(run_startup(json.dumps(cfg)), f"{bmc_key} BMC network")

    def test_exceptions_overlapping_each_other_refuse(self):
        cfg = _with_exceptions(EXCEPTION)
        cfg["site2"]["pool-exceptions"] = ["172.20.5.0/24"]
        assert_refused(run_startup(json.dumps(cfg)),
                       "overlaps site 'site2' pool-exceptions entry")

    def test_a_bad_pool_and_a_bad_exception_are_both_reported(self):
        """parse_site_networks collects every fault so one restart shows them
        all — exceptions are parsed even when that site's pool did not."""
        cfg = {"site1": {"pool": "not-a-cidr", "pool-exceptions": ["also-not-a-cidr"]}}
        assert_refused(run_startup(json.dumps(cfg)),
                       "invalid pool CIDR",
                       "invalid pool-exceptions[0] CIDR")


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
