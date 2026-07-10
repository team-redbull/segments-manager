"""Database utilities module for Segments Manager.

This module provides a unified DatabaseUtils class that aggregates all database operations
from specialized utility modules. This maintains backward compatibility with existing code.

Module structure:
- allocation_utils.py: Allocation operations (find, allocate, release)
- segment_crud.py: Basic CRUD operations (create, read, update, delete)
- segment_queries.py: Search and filter operations
- statistics_utils.py: Statistics and aggregation
"""

from .allocation_utils import AllocationUtils
from .segment_crud import SegmentCRUD
from .segment_queries import SegmentQueries
from .statistics_utils import StatisticsUtils


class DatabaseUtils:
    """Unified database utilities class - aggregates all database operations for backward compatibility"""

    # Allocation operations
    find_existing_allocation = staticmethod(AllocationUtils.find_existing_allocation)
    find_and_allocate_segment = staticmethod(AllocationUtils.find_and_allocate_segment)
    find_available_segment = staticmethod(AllocationUtils.find_available_segment)
    allocate_segment = staticmethod(AllocationUtils.allocate_segment)
    release_segment = staticmethod(AllocationUtils.release_segment)

    # CRUD operations
    create_segment = staticmethod(SegmentCRUD.create_segment)
    get_segment_by_id = staticmethod(SegmentCRUD.get_segment_by_id)
    update_segment_by_id = staticmethod(SegmentCRUD.update_segment_by_id)
    delete_segment_by_id = staticmethod(SegmentCRUD.delete_segment_by_id)

    # Query operations
    get_segments_with_filters = staticmethod(SegmentQueries.get_segments_with_filters)
    check_vlan_exists = staticmethod(SegmentQueries.check_vlan_exists)
    check_vlan_exists_excluding_id = staticmethod(SegmentQueries.check_vlan_exists_excluding_id)
    search_segments = staticmethod(SegmentQueries.search_segments)

    # Statistics operations
    get_site_statistics = staticmethod(StatisticsUtils.get_site_statistics)


# Export all classes for direct import if needed
__all__ = [
    "DatabaseUtils",
    "AllocationUtils",
    "SegmentCRUD",
    "SegmentQueries",
    "StatisticsUtils",
]
