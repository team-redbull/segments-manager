import os
import logging
import sys

from dotenv import load_dotenv

# Load .env for local development. Existing environment variables always take
# precedence (load_dotenv never overrides them), so container/Helm deployments
# that inject real env vars are unaffected. This module is the first project
# import on every entry path, so the file is loaded before any os.getenv call.
load_dotenv()

# MongoDB Configuration
MONGODB_URL = os.getenv("MONGODB_URL")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "segments_manager")

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

# Segment-connectivity workflow API — base URL of the unified FastAPI service
# (api.py in the workflows repo) that starts the segment-connectivity workflow.
# Required: segment creation triggers it, so a missing URL must fail loudly at
# startup rather than silently skipping the trigger in production.
WORKFLOWS_API_URL = os.getenv("WORKFLOWS_API_URL")

if not WORKFLOWS_API_URL:
    error_msg = (
        "CRITICAL CONFIGURATION ERROR: WORKFLOWS_API_URL environment variable is not set!\n"
        "Please set WORKFLOWS_API_URL in your environment or .env file.\n"
        "Example: export WORKFLOWS_API_URL='http://localhost:8080'"
    )
    print(f"ERROR: {error_msg}", file=sys.stderr)
    raise ValueError(error_msg)

WORKFLOWS_API_URL = WORKFLOWS_API_URL.rstrip("/")

# Site IP Prefix Configuration — the single source of truth for configured
# sites. SITES is derived from its keys rather than being its own env var,
# so the two can never drift out of sync.
# Format: "site1:192,site2:193,site3:194"
SITE_PREFIXES_ENV = os.getenv("SITE_PREFIXES", "")


def parse_site_prefixes(site_prefixes_str: str) -> dict:
    """Parse site prefixes from environment variable.

    Format: "site1:192,site2:193,site3:194"
    Returns: {"site1": "192", "site2": "193", ...}
    """
    prefixes = {}
    if not site_prefixes_str:
        return prefixes
    for pair in site_prefixes_str.split(","):
        if ":" in pair:
            site, prefix = pair.strip().split(":", 1)
            prefixes[site.strip()] = prefix.strip()
    return prefixes


SITE_IP_PREFIXES = parse_site_prefixes(SITE_PREFIXES_ENV)
SITES = list(SITE_IP_PREFIXES.keys())


def validate_site_prefixes():
    """Validate that at least one site is configured. Fail fast at startup."""
    if not SITE_IP_PREFIXES:
        error_msg = (
            "CRITICAL CONFIGURATION ERROR: No site IP prefixes configured!\n"
            "Please set SITE_PREFIXES environment variable.\n"
            "Example: SITE_PREFIXES=\"site1:192,site2:193,site3:194\""
        )
        print(f"ERROR: {error_msg}", file=sys.stderr)
        raise ValueError(error_msg)

    print(f"INFO: Site IP prefixes validated for sites: {SITES}", file=sys.stderr)


def get_site_prefix(site: str) -> str:
    """Get the IP prefix for a given site.

    Returns the prefix string (e.g. "192") or None if not found.
    """
    prefix = SITE_IP_PREFIXES.get(site)
    if prefix:
        return prefix
    # Case-insensitive fallback
    site_lower = site.lower()
    for key, val in SITE_IP_PREFIXES.items():
        if key.lower() == site_lower:
            return val
    return None


# Logging Configuration
# Path to the rotating log file. Defaults to the current directory for local
# runs; in the container it is set to a writable location (see Dockerfile /
# Helm), because the app runs as a non-root user that cannot write to /app.
LOG_FILE = os.getenv("LOG_FILE", "segments_manager.log")


def setup_logging():
    """Configure logging with a stdout handler and a rotating file handler.

    File logging is best-effort: if the log file cannot be opened (e.g. the
    non-root container user lacks write permission on the target directory),
    the app logs a warning and continues with stdout only instead of crashing.
    """
    from logging.handlers import RotatingFileHandler

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] %(funcName)s() - %(message)s'

    handlers = [logging.StreamHandler(sys.stdout)]
    file_handler_error = None
    try:
        handlers.append(RotatingFileHandler(
            LOG_FILE,
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        ))
    except OSError as e:  # includes PermissionError
        file_handler_error = e

    logging.basicConfig(level=log_level, format=log_format, handlers=handlers)
    logger = logging.getLogger(__name__)

    if file_handler_error is not None:
        logger.warning(
            f"File logging disabled: could not open log file '{LOG_FILE}' "
            f"({file_handler_error}). Logging to stdout only. "
            f"Set LOG_FILE to a writable path to enable file logging and the /api/logs endpoint."
        )
    return logger


# Server Configuration
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
