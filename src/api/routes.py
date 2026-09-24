from typing import Optional, List
import logging
from fastapi import APIRouter, HTTPException

from ..models.schemas import (
    SegmentAllocationRequest, SegmentAllocationResponse,
    SegmentRelease, Segment,
    SegmentDhcpUpdate, SegmentClustersUpdate
)
from ..services.allocation_service import AllocationService
from ..services.segment_service import SegmentService
from ..services.stats_service import StatsService
from ..services.logs_service import LogsService
from ..services.export_service import ExportService
from ..database.cache import invalidate_cache, CACHE_KEY_SEGMENTS

router = APIRouter()

# Segment Management Routes
@router.get("/segments")
async def get_segments(
    site: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    fresh: bool = False,
):
    """Get segments with optional filters (status: Available | Allocated).

    Only Allocated segments have a type, so a `type` filter never matches an
    Available one.

    fresh=true drops the server-side segments cache first, so edits made
    directly in MongoDB show up immediately (the UI's Refresh button).
    """
    if fresh:
        invalidate_cache(CACHE_KEY_SEGMENTS)
    return await SegmentService.get_segments(site, status, type)

@router.get("/segments/search")
async def search_segments(
    q: str,
    site: Optional[str] = None,
    status: Optional[str] = None
):
    """Search segments by cluster name, EPG name, VLAN ID, or segment"""
    return await SegmentService.search_segments(q, site, status)

@router.post("/segments")
async def create_segment(
    segment: Segment
):
    """Create a new segment"""
    return await SegmentService.create_segment(segment)

# Single-segment routes are keyed by the segment CIDR — the natural key
# (unique + immutable) — never by the internal Mongo ObjectId. The CIDR
# contains a "/" so it can't live in a path: reads/deletes take it as a
# query parameter, mutations carry it in the request body.

@router.get("/segments/by-segment")
async def get_segment(segment: str):
    """Get a single segment by its CIDR value (e.g. ?segment=192.168.1.0/24)"""
    return await SegmentService.get_segment_by_segment(segment)

@router.patch("/segments")
async def update_segment_dhcp(
    request: SegmentDhcpUpdate
):
    """Update a segment's DHCP flag — the only in-place-editable segment field.

    Identity fields (site, vlan_id, epg_name, segment) are immutable after
    creation; lifecycle fields (status, type, cluster_name) are managed by the
    allocation endpoints.
    """
    return await SegmentService.update_segment_dhcp(request.segment, request.dhcp)

@router.put("/segments/clusters")
async def update_segment_clusters(
    request: SegmentClustersUpdate
):
    """Assign a segment to a single cluster, as a given type.

    `type` is required with a cluster_name — an allocated segment always has
    one. Empty or omitted cluster_name releases the segment and clears its type.
    """
    return await SegmentService.update_segment_clusters(
        request.segment, request.cluster_name, request.type
    )

@router.delete("/segments")
async def delete_segment(segment: str):
    """Delete a segment identified by its CIDR value (e.g. ?segment=192.168.1.0/24)"""
    return await SegmentService.delete_segment(segment)

@router.post("/segments/bulk")
async def create_segments_bulk(
    segments: List[Segment]
):
    """Create multiple segments at once"""
    logger = logging.getLogger(__name__)
    
    if not segments or len(segments) == 0:
        logger.warning("Bulk create called with empty segments list")
        raise HTTPException(status_code=400, detail="No segments provided. Please check your CSV data format.")
    
    logger.info(f"Received bulk create request with {len(segments)} segments")
    return await SegmentService.create_segments_bulk(segments)

# Segment Allocation Routes
#
# Allocation acts on the segment collection — it picks a member out of the
# available pool rather than addressing a known CIDR — so both routes hang off
# /segments like every other sub-route.

@router.post("/segments/allocate", response_model=SegmentAllocationResponse)
async def allocate_segment(
    request: SegmentAllocationRequest
):
    """Allocate a VLAN segment for a cluster at a site, as a given type.

    Available segments have no type: any one at the site is handed out and
    becomes `type`. Idempotent per (cluster_name, site, type): a cluster that
    already holds a segment of that type at that site gets the same one back.
    """
    return await AllocationService.allocate_segment(request)

@router.post("/segments/release")
async def release_segment(
    request: SegmentRelease
):
    """Release a segment identified by its CIDR value (status Allocated -> Available).

    Keyed by the segment CIDR because it is globally unique, so no site,
    cluster name or type is needed.

    Clears the segment's type along with its cluster. Idempotent for an
    already-"Available" segment (200): the lifecycle has exactly two states,
    so every segment is releasable.
    """
    return await AllocationService.release_segment(request.segment)

# Statistics and Configuration Routes
@router.get("/sites")
async def get_sites():
    """Get configured sites"""
    return await StatsService.get_sites()

@router.get("/stats")
async def get_stats():
    """Get statistics per site"""
    return await StatsService.get_stats()

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return await StatsService.health_check()

# Export Routes
@router.get("/export/segments/csv")
async def export_segments_csv(
    site: Optional[str] = None,
    status: Optional[str] = None
):
    """Export segments data as CSV"""
    return await ExportService.export_segments_csv(site=site, status=status)

@router.get("/export/segments/excel")
async def export_segments_excel(
    site: Optional[str] = None,
    status: Optional[str] = None
):
    """Export segments data as Excel"""
    return await ExportService.export_segments_excel(site=site, status=status)

@router.get("/export/stats/csv")
async def export_stats_csv():
    """Export site statistics as CSV"""
    return await ExportService.export_stats_csv()

# Logs Management Routes
@router.get("/logs")
async def get_logs(lines: int = 100):
    """Get the contents of the segments_manager.log file
    
    Args:
        lines: Number of lines to retrieve from the end of the log file (default: 100)
    """
    return await LogsService.get_logs(lines)

@router.get("/logs/info")
async def get_log_info():
    """Get information about the log file (size, location, etc.)"""
    return await LogsService.get_log_info()