"""Allocation utilities for VLAN segment management.

Handles all allocation-related operations including finding allocations,
atomic allocation, and releasing segments.
"""

import logging
import time
from typing import Optional, Dict, Any

from ...database import (
    STATUS_AVAILABLE,
    STATUS_ALLOCATED,
    get_segments,
    update_segment as _update_segment,
    allocate_segment as _allocate_segment,
)
from ..time_utils import get_current_utc

logger = logging.getLogger(__name__)


class AllocationUtils:
    """Utilities for segment allocation operations"""

    @staticmethod
    async def find_existing_allocation(cluster_name: str, site: str, type: str) -> Optional[Dict[str, Any]]:
        """Find an existing allocation of the given type for a cluster at a site.

        `cluster_name` holds exactly one cluster (one segment is never shared by
        many clusters), so an exact match is the whole search.
        """
        candidates = await get_segments(
            site=site, cluster_name=cluster_name, status=STATUS_ALLOCATED, type=type
        )
        return candidates[0] if candidates else None

    @staticmethod
    async def find_and_allocate_segment(site: str, cluster_name: str, type: str) -> Optional[Dict[str, Any]]:
        """Atomically find and allocate an available segment of a type for a site."""
        logger.info(f"Allocating from site={site}, type={type}")
        t1 = time.time()
        result = await _allocate_segment(
            site=site, cluster_name=cluster_name, type=type, sort_by_vlan_id=True
        )
        logger.info(f"allocate_segment took {(time.time() - t1)*1000:.0f}ms")
        return result

    @staticmethod
    async def find_available_segment(site: str) -> Optional[Dict[str, Any]]:
        """Find an available segment for a site (kept for backward compatibility)."""
        segments = await get_segments(site=site, status=STATUS_AVAILABLE)
        return segments[0] if segments else None

    @staticmethod
    async def allocate_segment(segment_id: str, cluster_name: str) -> bool:
        """Allocate a segment to a cluster (kept for backward compatibility)."""
        allocation_time = get_current_utc()
        return await _update_segment(segment_id, {
            "status": STATUS_ALLOCATED,
            "cluster_name": cluster_name,
            "allocated_at": allocation_time,
        })

    @staticmethod
    async def release_segment(segment_id: str) -> bool:
        """Release an allocated segment by id (Allocated -> Available).

        Callers resolve the segment from its CIDR first, so there is no cluster
        matching to do here.
        """
        return await _update_segment(segment_id, {
            "status": STATUS_AVAILABLE,
            "cluster_name": None,
        })
