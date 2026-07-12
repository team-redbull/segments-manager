"""Client for the Cluster Orchestrator's connectivity workflow trigger.

POST /workflows/connectivity on that service starts a Temporal workflow and
returns 202 immediately — the workflow itself (firewall approval) can take
days, but this call is just the ack round-trip. It is fired after a segment
is durably created in MongoDB and is best-effort: any failure (timeout,
connection error, non-2xx) is logged and swallowed so it can never turn a
successful segment creation into a failed API response. The workflow decides
which segment types connectivity is implemented for — the trigger is sent
unconditionally.
"""

import logging

import httpx

from ..config.constants import WorkflowTrigger
from ..config.settings import WORKFLOWS_API_URL

logger = logging.getLogger(__name__)


async def trigger_connectivity_workflow(segment: str, segment_type: str) -> None:
    """Best-effort trigger of the connectivity workflow for a newly created segment.

    Never raises — any exception here would otherwise propagate through
    @handle_db_errors and turn an already-successful segment creation into a
    500 response, which would be misleading to the caller.
    """
    url = f"{WORKFLOWS_API_URL}/workflows/connectivity"
    try:
        async with httpx.AsyncClient(timeout=WorkflowTrigger.TIMEOUT_SECONDS) as client:
            response = await client.post(url, json={"segment": segment, "type": segment_type})
        if response.status_code == 409:
            logger.info(f"Connectivity workflow already running for segment {segment}")
        elif response.is_error:
            logger.warning(
                f"Connectivity workflow trigger for segment {segment} returned "
                f"{response.status_code}: {response.text}"
            )
        else:
            logger.info(f"Triggered connectivity workflow for segment {segment}: {response.json()}")
    except Exception as e:  # noqa: BLE001 — best-effort trigger must never fail the caller
        logger.warning(f"Failed to trigger connectivity workflow for segment {segment}: {e}")
