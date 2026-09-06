import os
import json
import logging
import ipaddress
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env for local development. Existing environment variables always take
# precedence (load_dotenv never overrides them), so container/Helm deployments
# that inject real env vars are unaffected. This module is the first project
# import on every entry path, so the file is loaded before any os.getenv call.
load_dotenv()

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "segments_manager")
# Collection holding the segment documents. Configurable so one database can
# host several independent segment sets (e.g. a scratch collection alongside
# production); the default is what every existing deployment already uses.
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "segments")

# When true, skip TLS certificate verification for the MongoDB connection
# (equivalent to "verify: false"). Keeps the connection encrypted but does not
# validate the server certificate/CA — useful for Atlas or self-hosted Mongo
# where the CA chain is unavailable. Do NOT enable in production if avoidable.
MONGODB_TLS_INSECURE = os.getenv("MONGODB_TLS_INSECURE", "false").strip().lower() in (
    "true", "1", "yes", "on",
)

if not MONGODB_URL:
    error_msg = (
        "CRITICAL CONFIGURATION ERROR: MONGODB_URL environment variable is not set!\n"
        "Please set MONGODB_URL in your environment or .env file.\n"
        "Example: export MONGODB_URL='mongodb://localhost:27017'"
    )
    print(f"ERROR: {error_msg}", file=sys.stderr)
    raise ValueError(error_msg)

# NOTE: this service no longer knows about the workflows API. Segment creation
# used to fire a best-effort trigger at it (WORKFLOWS_API_URL), which put the
# creation itself outside Temporal — invisible in the Temporal UI, and silently
# skipped whenever that call failed. The direction is now reversed: the
# segment-connectivity workflow is triggered directly by its caller and calls
# POST /api/segments here as its own first step, so one Temporal run covers the
# whole lifecycle. This service is a plain dependency of that workflow and
# triggers nothing.

# Site Network Configuration — the single source of truth for configured sites.
# SITES is derived from its keys rather than being its own env var, so the two
# can never drift out of sync.
#
# JSON object keyed by site name:
#   {"site1": {"pool": "192.10.0.0/16",
#              "dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"}, ...}
#
#   pool       the /16 (or narrower) every segment at that site must fall INSIDE.
#              Read on every create — see NetworkValidators.validate_segment_format.
#   dell-bmc   the site's static out-of-band management networks, ONE PER SERVER
#   cisco-bmc  HARDWARE VENDOR — Dell and Cisco BMCs sit on separate /16s. This
#              service never reads them per-request; they exist here only so
#              startup can check that no pool collides with a management network.
#              The segment-connectivity workflow is the component that actually
#              uses them (it opens firewall rules from each MCE segment to both).
#
# The same structure is consumed by segment-connectivity, so wherever an
# environment defines it, it must be defined ONCE and rendered into both
# services' config — a per-service copy is how the two site lists drift apart.
# In a Helm/Argo CD deployment that is the chart's `siteNetworks` value, which
# renders this env var into the ConfigMap. Sub-keys this service does not
# recognise are ignored on purpose — another consumer may own them.
SITE_NETWORKS_ENV = os.getenv("SITE_NETWORKS", "")

# Superseded by SITE_NETWORKS. Read only to detect a stale ConfigMap; never used.
_LEGACY_SITE_PREFIXES_ENV = os.getenv("SITE_PREFIXES", "")

_BMC_KEYS = ("dell-bmc", "cisco-bmc")

_SITE_NETWORKS_EXAMPLE = (
    'SITE_NETWORKS=\'{"site1": {"pool": "192.10.0.0/16", '
    '"dell-bmc": "10.50.0.0/16", "cisco-bmc": "10.60.0.0/16"}, '
    '"site2": {"pool": "193.51.0.0/16", '
    '"dell-bmc": "10.51.0.0/16", "cisco-bmc": "10.61.0.0/16"}}\''
)


def parse_site_networks(raw: str):
    """Parse and validate the SITE_NETWORKS JSON topology.

    Returns (networks, pools, errors). Never raises — every problem is appended
    to `errors` so startup can report all of them at once. The raise happens in
    validate_site_networks(), not at import: src/app.py already has a
    validate-then-log lifespan, and raising here would make this module
    un-importable (breaking tests and any tooling that reads settings).

    networks  {site: {sub-key: raw value}} — the untouched parsed JSON per site
    pools     {site: IPv4Network} — parsed once here so request validation does
              no re-parsing
    """
    networks: dict = {}
    pools: dict = {}
    errors: list = []

    if not raw.strip():
        errors.append("SITE_NETWORKS is not set")
        return networks, pools, errors

    try:
        parsed = json.loads(raw)
    except ValueError as e:
        errors.append(f"SITE_NETWORKS is not valid JSON: {e}")
        # The old format is a comma/colon string, not JSON. Say so explicitly —
        # otherwise a half-migrated ConfigMap just looks like a typo.
        if ":" in raw and "{" not in raw:
            errors.append(
                "the value looks like the legacy SITE_PREFIXES format "
                '("site1:192,site2:193"). It was replaced by the JSON topology below.'
            )
        return networks, pools, errors

    if not isinstance(parsed, dict) or not parsed:
        errors.append("SITE_NETWORKS must be a non-empty JSON object keyed by site name")
        return networks, pools, errors

    seen_lower: dict = {}
    for site, value in parsed.items():
        if not site or not site.strip():
            errors.append("SITE_NETWORKS contains an empty site name")
            continue

        # Site lookup is case-insensitive (see resolve_site), so two names that
        # differ only in case would make it ambiguous which one wins.
        lower = site.lower()
        if lower in seen_lower:
            errors.append(
                f"sites '{seen_lower[lower]}' and '{site}' differ only by case; "
                f"site lookup is case-insensitive"
            )
            continue
        seen_lower[lower] = site

        if not isinstance(value, dict):
            errors.append(
                f"site '{site}' maps to a {type(value).__name__}, expected an object "
                f'with a "pool" key'
            )
            continue
        if "pool" not in value:
            errors.append(f'site \'{site}\' has no "pool" key')
            continue

        pool = _parse_cidr(site, "pool", value["pool"], errors)
        if pool is not None:
            pools[site] = pool
        # The BMC keys are optional here (this service never reads them per
        # request); parsed only to validate them and to check disjointness.
        # There is one per server hardware vendor — see the header.
        for bmc_key in _BMC_KEYS:
            if bmc_key in value:
                _parse_cidr(site, bmc_key, value[bmc_key], errors)

        networks[site] = value

    errors.extend(_find_overlaps(parsed, pools))
    return networks, pools, errors


def _parse_cidr(site: str, key: str, value, errors: list):
    """Parse one CIDR sub-key, appending a specific message on failure."""
    try:
        # strict=True: "192.10.0.1/16" is an operator error, not something to
        # silently normalise away — the config should say what it means.
        network = ipaddress.ip_network(value, strict=True)
    except (ValueError, TypeError) as e:
        errors.append(f"site '{site}': invalid {key} CIDR {value!r}: {e}")
        return None
    if network.version != 4:
        # The rest of the validation stack is IPv4-only (see the octet handling
        # in NetworkValidators.validate_no_reserved_ips).
        errors.append(f"site '{site}': {key} must be IPv4, got {value!r}")
        return None
    return network


def _find_overlaps(parsed: dict, pools: dict) -> list:
    """Check that no pool overlaps another pool or any site's BMC networks.

    Two overlapping pools would make site containment ambiguous. A pool
    overlapping a BMC network means segments would be allocated on top of an
    out-of-band management network. Neither is detectable anywhere else: request
    validation checks containment first, and pools are disjoint from the BMC
    ranges by design, so no segment that passes containment can ever reach a BMC
    conflict. Startup is the only place these can be caught.

    Every vendor's BMC network is checked, not just one: a site has a Dell and a
    Cisco management /16, and a pool colliding with either is the same fault.
    Deliberately NOT checked: BMC-vs-BMC overlap. This service owns `pool`, and
    inventing invariants over keys it never reads is how the two services'
    validation drifts apart.
    """
    errors = []
    sites = list(pools)

    for i, site_a in enumerate(sites):
        for site_b in sites[i + 1:]:
            if pools[site_a].overlaps(pools[site_b]):
                errors.append(
                    f"site '{site_a}' pool {pools[site_a]} overlaps "
                    f"site '{site_b}' pool {pools[site_b]}"
                )

    for bmc_site, value in parsed.items():
        if not isinstance(value, dict):
            continue
        for bmc_key in _BMC_KEYS:
            if bmc_key not in value:
                continue
            try:
                bmc = ipaddress.ip_network(value[bmc_key], strict=True)
            except (ValueError, TypeError):
                continue  # already reported by _parse_cidr
            for pool_site, pool in pools.items():
                if pool.overlaps(bmc):
                    errors.append(
                        f"site '{pool_site}' pool {pool} overlaps site "
                        f"'{bmc_site}' {bmc_key} BMC network {bmc}"
                    )
    return errors


SITE_NETWORKS, SITE_POOLS, _SITE_NETWORKS_ERRORS = parse_site_networks(SITE_NETWORKS_ENV)
SITES = list(SITE_NETWORKS.keys())


def validate_site_networks():
    """Validate the site topology. Fail fast at startup."""
    # New code against a stale ConfigMap. Fail rather than start with no sites —
    # the alternative is a Healthy pod that rejects every create.
    if _LEGACY_SITE_PREFIXES_ENV and not SITE_NETWORKS_ENV.strip():
        error_msg = (
            "CRITICAL CONFIGURATION ERROR: SITE_PREFIXES is set but SITE_NETWORKS is not.\n"
            "SITE_PREFIXES was replaced by SITE_NETWORKS (a JSON site topology) and is\n"
            "no longer read. This process is running new code against a stale config.\n"
            f"{_SITE_NETWORKS_EXAMPLE}\n"
            "Fix: set SITE_NETWORKS in whatever supplies this deployment's\n"
            "environment — the ConfigMap on Kubernetes, the .env or -e flags\n"
            "elsewhere — and remove SITE_PREFIXES. Under Helm/Argo CD it is the\n"
            "chart's `siteNetworks` value that renders SITE_NETWORKS into the\n"
            "ConfigMap, so a pod seeing this is running a new image against an\n"
            "old chart revision or a hand-edited ConfigMap."
        )
        print(f"ERROR: {error_msg}", file=sys.stderr)
        raise ValueError(error_msg)

    if _SITE_NETWORKS_ERRORS:
        error_msg = (
            "CRITICAL CONFIGURATION ERROR: SITE_NETWORKS is invalid!\n"
            + "\n".join(f"  - {e}" for e in _SITE_NETWORKS_ERRORS)
            + f"\n{_SITE_NETWORKS_EXAMPLE}"
        )
        print(f"ERROR: {error_msg}", file=sys.stderr)
        raise ValueError(error_msg)

    # Both set is the expand/contract rollout window: the ConfigMap carries the
    # old key and the new one while images roll. Warn, don't fail.
    if _LEGACY_SITE_PREFIXES_ENV:
        print(
            "WARNING: SITE_PREFIXES is set and IGNORED (superseded by SITE_NETWORKS). "
            "Remove it from the ConfigMap once every replica is on the new image.",
            file=sys.stderr,
        )

    summary = ", ".join(f"{site}={pool}" for site, pool in SITE_POOLS.items())
    print(f"INFO: Site networks validated: {summary}", file=sys.stderr)

    # A typo'd sub-key (e.g. "dell-bcm") is silently ignored here but crash-loops
    # the segment-connectivity worker, which requires both BMC keys. Surface it in
    # this log too. A bare "bmc" lands here as well: it is the pre-vendor-split
    # key, and a ConfigMap still carrying it has not been migrated.
    for site, value in SITE_NETWORKS.items():
        unknown = sorted(set(value) - {"pool", *_BMC_KEYS})
        if unknown:
            print(
                f"INFO: site '{site}' has unrecognised SITE_NETWORKS sub-keys "
                f"{unknown} (ignored by this service)",
                file=sys.stderr,
            )


def resolve_site(site: str):
    """Return the canonical configured name for `site`, or None if unknown.

    Lookup is case-insensitive. This is the one place that rule lives — both
    InputValidators.validate_site and the pool lookup go through it, so a
    request for "Site1" cannot pass one and fail the other.
    """
    if site in SITE_NETWORKS:
        return site
    site_lower = site.lower()
    for key in SITE_NETWORKS:
        if key.lower() == site_lower:
            return key
    return None


def get_site_pool(site: str):
    """Return the site's allocatable pool as an IPv4Network, or None if unknown."""
    canonical = resolve_site(site)
    return SITE_POOLS.get(canonical) if canonical else None


def get_site_networks(site: str):
    """Return the site's raw topology dict (pool, dell-bmc, ...), or None if unknown."""
    canonical = resolve_site(site)
    return SITE_NETWORKS.get(canonical) if canonical else None


# Logging Configuration
# Not configurable. Derived from the package root so the one constant is correct
# in both places the app runs: `/app/data/segments_manager.log` in the container
# (the Dockerfile creates that directory world-writable, so it works whatever UID
# the platform assigns) and `<repo>/data/segments_manager.log` for a local run.
# The old LOG_FILE env var let a deployment point this at /app, which is not
# writable under a non-root securityContext — a ConfigMap key whose only real
# effect was to silently disable file logging and /api/logs.
LOG_FILE = str(Path(__file__).resolve().parents[2] / "data" / "segments_manager.log")

# Not configurable: this service logs at INFO. Nothing below INFO is worth the
# volume in production, and DEBUG on a request path leaks segment data into logs.
LOG_LEVEL = logging.INFO


def setup_logging():
    """Configure logging with a stdout handler and a rotating file handler.

    File logging is best-effort: if the log file cannot be opened (e.g. the
    non-root container user lacks write permission on the target directory),
    the app logs a warning and continues with stdout only instead of crashing.
    """
    from logging.handlers import RotatingFileHandler

    log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s() - %(message)s'

    handlers = [logging.StreamHandler(sys.stdout)]
    file_handler_error = None
    try:
        # The container image ships this directory; create it for local runs.
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            LOG_FILE,
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        ))
    except OSError as e:  # includes PermissionError
        file_handler_error = e

    logging.basicConfig(level=LOG_LEVEL, format=log_format, handlers=handlers)
    logger = logging.getLogger(__name__)

    if file_handler_error is not None:
        logger.warning(
            f"File logging disabled: could not open log file '{LOG_FILE}' "
            f"({file_handler_error}). Logging to stdout only, and /api/logs will "
            f"return 404. The path is fixed; make its directory writable by the "
            f"user this process runs as."
        )
    return logger


# Server Configuration
# The bind address is not configurable: in a container the app owns its network
# namespace, so binding anything narrower than every interface only breaks the
# kubelet's probes. The port stays configurable — it has to match the chart's
# service.targetPort.
SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
