import logging
from typing import Dict, Any
from fastapi import HTTPException

from ..database import STATUS_ALLOCATED
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
        """Allocate a VLAN segment for a cluster at a site, as the requested type.

        Available segments carry no type: any of them at the site is handed
        out, and becomes `request.type` in the same atomic update.
        """
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

        # Atomically take any available segment at this site and stamp the type on it
        allocated_segment = await DatabaseUtils.find_and_allocate_segment(
            request.site, request.cluster_name, request.type
        )

        if not allocated_segment:
            raise HTTPException(
                status_code=503,
                detail=f"No available segments for site: {request.site}"
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

        Keyed by the CIDR because it is globally unique, so it alone identifies
        the allocation.

        The lifecycle is two-way and has exactly two states, so release is
        total — every segment is either Allocated or Available:
          "Allocated" -> released (status "Available", cluster_name and type
                         cleared — both were set by the allocation)
          "Available" -> no-op, HTTP 200. Release is idempotent so a retried
                         call is safe; the segment is already in the state the
                         caller asked for.
        """
        logger.info(f"Release request: segment={segment}")

        existing = await DatabaseUtils.get_segment_by_segment(segment)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Segment not found: {segment}")

        status = existing.get("status")

        if status != STATUS_ALLOCATED:
            return {"message": "Segment already released"}

        success = await DatabaseUtils.release_segment(str(existing["_id"]))
        if not success:
            raise HTTPException(status_code=500, detail="Failed to release segment")

        logger.info(f"Released segment {segment} (was allocated to {existing.get('cluster_name')})")
        return {"message": "Segment released successfully"}
