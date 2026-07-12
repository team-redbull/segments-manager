"""CRUD operations for VLAN segments.

Handles create, read, update, delete operations for segments.
"""

import logging
from typing import Optional, Dict, Any

from ...database import (
    create_segment as _create_segment,
    get_segment_by_segment as _get_segment_by_segment,
    update_segment as _update_segment,
    delete_segment as _delete_segment,
)

logger = logging.getLogger(__name__)


class SegmentCRUD:
    """Basic CRUD operations for segments"""

    @staticmethod
    async def create_segment(segment_data: Dict[str, Any]) -> str:
        """Create a new segment

        Returns:
            Segment ID as string
        """
        new_segment = {
            **segment_data,
            "cluster_name": None,
            "allocated_at": None,
            "released": False,
            "released_at": None
        }

        result = await _create_segment(new_segment)
        # _create_segment returns a dict with "_id" field, extract it
        if isinstance(result, dict) and "_id" in result:
            return str(result["_id"])
        elif isinstance(result, str):
            return result
        else:
            logger.warning(f"Unexpected return type from create_segment: {type(result)}, value: {result}")
            return str(result.get("_id", result)) if isinstance(result, dict) else str(result)

    @staticmethod
    async def get_segment_by_segment(segment: str) -> Optional[Dict[str, Any]]:
        """Get segment by its CIDR value (unique)"""
        return await _get_segment_by_segment(segment)

    @staticmethod
    async def update_segment_by_id(segment_id: str, update_data: Dict[str, Any]) -> bool:
        """Update segment by ID"""
        return await _update_segment(segment_id, update_data)

    @staticmethod
    async def delete_segment_by_id(segment_id: str) -> bool:
        """Delete segment by ID"""
        return await _delete_segment(segment_id)
