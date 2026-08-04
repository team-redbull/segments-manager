import logging
from typing import Dict, Any
from fastapi import HTTPException

from ..database import STATUS_ALLOCATED, STATUS_LOCKED
from ..models.schemas import SegmentAllocationRequest, SegmentAllocationResponse
from ..utils.database_utils import DatabaseUtils
from ..utils.validators import Validators
from ..utils.error_handlers import handle_db_errors, retry_on_network_error
from ..utils.logging_decorators import log_operation_timing

logger = logging.getLogger(__name__)

class AllocationService:
    """Service class for segment allocation operations"""

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("allocate_segment", threshold_ms=2000)
    async def allocate_segment(request: SegmentAllocationRequest) -> SegmentAllocationResponse:
        """Allocate a VLAN segment of the requested type for a cluster at a site."""
        logger.info(
            f"Allocation request: cluster={request.cluster_name}, site={request.site}, type={request.type}"
        )

        Validators.validate_site(request.site)
        Validators.validate_cluster_name(request.cluster_name)

        # Check if cluster already has an allocation of this type at this site.
        # Scoped by type so a cluster can hold e.g. both an MCE and an HC segment.
        existing = await DatabaseUtils.find_existing_allocation(
            request.cluster_name, request.site, request.type
        )

        if existing:
            logger.info(f"Returning existing allocation: VLAN {existing['vlan_id']} for {request.cluster_name}")
            return SegmentAllocationResponse(
                vlan_id=existing["vlan_id"],
                cluster_name=existing["cluster_name"],
                site=existing["site"],
                type=existing["type"],
                segment=existing["segment"],
                epg_name=existing["epg_name"],
                allocated_at=existing["allocated_at"]
            )

        # Atomically find and allocate an available segment of this type for this site
        allocated_segment = await DatabaseUtils.find_and_allocate_segment(
            request.site, request.cluster_name, request.type
        )

        if not allocated_segment:
            raise HTTPException(
                status_code=503,
                detail=f"No available {request.type} segments for site: {request.site}"
            )

        logger.info(f"Allocated VLAN {allocated_segment['vlan_id']} (EPG: {allocated_segment['epg_name']}) to {request.cluster_name}")

        return SegmentAllocationResponse(
            vlan_id=allocated_segment["vlan_id"],
            cluster_name=request.cluster_name,
            site=request.site,
            type=allocated_segment["type"],
            segment=allocated_segment["segment"],
            epg_name=allocated_segment["epg_name"],
            allocated_at=allocated_segment["allocated_at"]
        )

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("release_segment", threshold_ms=2000)
    async def release_segment(segment: str) -> Dict[str, str]:
        """Release a segment identified by its CIDR (status "Allocated" -> "Available").

        Keyed by the CIDR just like unlock — it is globally unique, so it alone
        identifies the allocation. A shared segment is freed from all of its
        clusters at once.

        Status handling:
          "Allocated" -> released (status "Available", cluster_name cleared)
          "Available" -> no-op, HTTP 200. Release is idempotent so a retried
                         call is safe; the segment is already in the state the
                         caller asked for.
          "Locked"    -> HTTP 409. Nothing was ever allocated, so there is
                         nothing to release. Erroring also keeps release from
                         becoming a second path for "Locked" -> "Available";
                         only /segments/unlock performs that transition.
        """
        logger.info(f"Release request: segment={segment}")

        existing = await DatabaseUtils.get_segment_by_segment(segment)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Segment not found: {segment}")

        status = existing.get("status")

        if status == STATUS_LOCKED:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot release segment {segment}: status is 'Locked', not 'Allocated'. "
                    "A locked segment has never been allocated — use POST /api/segments/unlock "
                    "to make it available."
                ),
            )

        if status != STATUS_ALLOCATED:
            return {"message": "Segment already released"}

        success = await DatabaseUtils.release_segment(str(existing["_id"]))
        if not success:
            raise HTTPException(status_code=500, detail="Failed to release segment")

        logger.info(f"Released segment {segment} (was allocated to {existing.get('cluster_name')})")
        return {"message": "Segment released successfully"}
