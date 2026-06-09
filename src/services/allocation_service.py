import logging
from typing import Dict, Any
from fastapi import HTTPException

from ..models.schemas import VLANAllocationRequest, VLANAllocationResponse
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
    @log_operation_timing("allocate_vlan", threshold_ms=2000)
    async def allocate_vlan(request: VLANAllocationRequest) -> VLANAllocationResponse:
        """Allocate a VLAN segment for a cluster at a site."""
        logger.info(f"Allocation request: cluster={request.cluster_name}, site={request.site}")

        Validators.validate_site(request.site)
        Validators.validate_cluster_name(request.cluster_name)

        # Check if cluster already has an allocation at this site
        existing = await DatabaseUtils.find_existing_allocation(request.cluster_name, request.site)

        if existing:
            logger.info(f"Returning existing allocation: VLAN {existing['vlan_id']} for {request.cluster_name}")
            return VLANAllocationResponse(
                vlan_id=existing["vlan_id"],
                cluster_name=existing["cluster_name"],
                site=existing["site"],
                segment=existing["segment"],
                epg_name=existing["epg_name"],
                allocated_at=existing["allocated_at"]
            )

        # Atomically find and allocate an available segment for this site
        allocated_segment = await DatabaseUtils.find_and_allocate_segment(request.site, request.cluster_name)

        if not allocated_segment:
            raise HTTPException(
                status_code=503,
                detail=f"No available segments for site: {request.site}"
            )

        logger.info(f"Allocated VLAN {allocated_segment['vlan_id']} (EPG: {allocated_segment['epg_name']}) to {request.cluster_name}")

        return VLANAllocationResponse(
            vlan_id=allocated_segment["vlan_id"],
            cluster_name=request.cluster_name,
            site=request.site,
            segment=allocated_segment["segment"],
            epg_name=allocated_segment["epg_name"],
            allocated_at=allocated_segment["allocated_at"]
        )

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("release_vlan", threshold_ms=2000)
    async def release_vlan(cluster_name: str, site: str) -> Dict[str, str]:
        """Release a VLAN segment allocation."""
        logger.info(f"Release request: cluster={cluster_name}, site={site}")

        Validators.validate_site(site)
        Validators.validate_cluster_name(cluster_name)

        success = await DatabaseUtils.release_segment(cluster_name, site)

        if not success:
            raise HTTPException(status_code=404, detail="Allocation not found")

        logger.info(f"Released VLAN for {cluster_name} at {site}")
        return {"message": "VLAN released successfully"}
