from typing import Optional, List
import logging
from fastapi import APIRouter, HTTPException

from ..models.schemas import (
    SegmentAllocationRequest, SegmentAllocationResponse,
    SegmentRelease, SegmentUnlock, Segment,
    SegmentDhcpUpdate, SegmentClustersUpdate,
    SegmentConnectivityRequestsUpdate
)
from ..services.allocation_service import AllocationService
from ..services.segment_service import SegmentService
from ..services.stats_service import StatsService
from ..services.logs_service import LogsService
from ..services.export_service import ExportService

router = APIRouter()

# Segment Allocation Routes
@router.post("/allocate-segment", response_model=SegmentAllocationResponse)
async def allocate_segment(
    request: SegmentAllocationRequest
):
    """Allocate a VLAN segment for a cluster"""
    return await AllocationService.allocate_segment(request)

@router.post("/release-segment")
async def release_segment(
    request: SegmentRelease
):
    """Release a VLAN segment allocation"""
    return await AllocationService.release_segment(request.cluster_name, request.site)

# Segment Management Routes
@router.get("/segments")
async def get_segments(
    site: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
):
    """Get segments with optional filters (status: Locked | Available | Allocated)"""
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
    """Update a segment's DHCP flag — the only mutable segment field.

    All other fields (site, vlan_id, epg_name, segment) are immutable after
    creation; lifecycle fields are managed by their own endpoints.
    """
    return await SegmentService.update_segment_dhcp(request.segment, request.dhcp)

@router.put("/segments/clusters")
async def update_segment_clusters(
    request: SegmentClustersUpdate
):
    """Update cluster assignment for a segment (for shared segments).

    Empty or omitted cluster_names releases the segment.
    """
    return await SegmentService.update_segment_clusters(request.segment, request.cluster_names or "")

@router.put("/segments/connectivity-requests")
async def set_segment_connectivity_requests(
    request: SegmentConnectivityRequestsUpdate
):
    """Replace the pending connectivity request ids displayed for a segment.

    Set by the connectivity orchestrator after it submits firewall (open-rules)
    requests; the UI shows the ids beside the segment's status while they await
    approval. An empty list clears the display (all requests completed).
    Idempotent.
    """
    return await SegmentService.set_connectivity_requests(
        request.segment, request.request_ids, request.submitted_at
    )


@router.post("/segments/unlock")
async def unlock_segment(
    request: SegmentUnlock
):
    """Unlock a segment identified by its CIDR value (status Locked -> Available).

    New segments start with status "Locked" (firewall rules not yet open) and
    are excluded from automatic VLAN allocation until unlocked. Intended to be
    called by the service responsible for opening firewall rules once it has
    done so. This is a one-way lifecycle transition — there is no endpoint to
    re-lock a segment. Idempotent.
    """
    return await SegmentService.unlock_segment_by_segment(request.segment)

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