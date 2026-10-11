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
    release_cluster as _release_cluster,
)

logger = logging.getLogger(__name__)


class AllocationUtils:
    """Utilities for segment allocation operations"""

    @staticmethod
    async def find_existing_allocation(cluster_name: str, site: str, type: str) -> Optional[Dict[str, Any]]:
        """Find an existing allocation of the given type for a cluster at a site.

        The cluster filter is a membership test, so a cluster listed on a
        shared (UPI) segment finds that segment too.
        """
        candidates = await get_segments(
            site=site, cluster_name=cluster_name, status=STATUS_ALLOCATED, type=type
        )
        return candidates[0] if candidates else None

    @staticmethod
    async def find_and_allocate_segment(site: str, cluster_name: str, type: str) -> Optional[Dict[str, Any]]:
        """Atomically allocate any available segment at a site as the given type."""
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
    async def release_segment(segment_id: str) -> bool:
        """Release an allocated segment by id (Allocated -> Available).

        Callers resolve the segment from its CIDR first, so there is no cluster
        matching to do here. The type goes with the cluster: it was stamped on
        at allocation, and an Available segment has none.
        """
        return await _update_segment(segment_id, {
            "status": STATUS_AVAILABLE,
            "type": None,
            "cluster_name": None,
        })

    @staticmethod
    async def release_cluster(segment_id: str, cluster_name: str) -> bool:
        """Drop one cluster from a multi-cluster (UPI) segment by id; the
        segment is released (Allocated -> Available) when its last cluster goes.
        """
        return await _release_cluster(segment_id, cluster_name)
