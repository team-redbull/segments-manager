import os
import sys
import secrets
import logging

from starlette.requests import Request

logger = logging.getLogger(__name__)

# Static API token for authenticating write requests. REQUIRED — the app fails
# fast at startup if it is unset, so mutating API calls can never be left
# unprotected. Clients send it as an `Authorization: Bearer <API_TOKEN>` header.
#
# This is the ONLY credential: there is no username/password login or session.
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    _error_msg = (
        "CRITICAL CONFIGURATION ERROR: API_TOKEN environment variable is not set!\n"
        "It is required to authenticate write requests (POST/PUT/PATCH/DELETE).\n"
        "Set a long, random secret, e.g. export API_TOKEN=\"$(openssl rand -hex 32)\""
    )
    print(f"ERROR: {_error_msg}", file=sys.stderr)
    raise ValueError(_error_msg)


def verify_api_token(request: Request) -> bool:
    """Check for a valid `Authorization: Bearer <API_TOKEN>` header.

    Uses a constant-time comparison to avoid leaking the token via timing.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    return secrets.compare_digest(token, API_TOKEN)


def is_authenticated(request: Request) -> bool:
    """Return True if the request carries a valid API token."""
    return verify_api_token(request)
