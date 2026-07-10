from typing import Optional, List
import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Response, Request
from starlette.responses import JSONResponse

from ..models.schemas import (
    VLANAllocationRequest, VLANAllocationResponse,
    VLANRelease, Segment, LoginRequest, LoginResponse, AuthStatusResponse
)
from ..services.allocation_service import AllocationService
from ..services.segment_service import SegmentService
from ..services.stats_service import StatsService
from ..services.logs_service import LogsService
from ..services.export_service import ExportService
from ..auth.auth import require_auth, get_current_user, login, logout, get_session_token, SESSION_TTL_DAYS

router = APIRouter()

# Authentication Routes
@router.post("/auth/login", response_model=LoginResponse)
async def auth_login(request: LoginRequest, response: Response):
    """Login with username and password

    Returns a session token that can be used as Bearer token for API requests.
    For web UI, a cookie is also set automatically.
    """
    session_token = login(request.username, request.password)
    if session_token:
        # Set session cookie (for web UI) - matches session TTL
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
            max_age=SESSION_TTL_DAYS * 86400  # Convert days to seconds (7 days = 604800 seconds)
        )
        # Return token in response body (for API/curl clients)
        return LoginResponse(
            success=True, 
            message="Login successful",
            token=session_token
        )
    else:
        raise HTTPException(status_code=401, detail="Invalid username or password")

@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response):
    """Logout current user"""
    logout(request)
    response.delete_cookie(key="session_token")
    return {"success": True, "message": "Logged out successfully"}

@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status(current_user: bool = Depends(get_current_user)):
    """Check authentication status"""
    return AuthStatusResponse(authenticated=current_user)

# VLAN Management Routes
@router.post("/allocate-vlan", response_model=VLANAllocationResponse)
async def allocate_vlan(
    request: VLANAllocationRequest,
    _: bool = Depends(require_auth)
):
    """Allocate a VLAN segment for a cluster"""
    return await AllocationService.allocate_vlan(request)

@router.post("/release-vlan")
async def release_vlan(
    request: VLANRelease,
    _: bool = Depends(require_auth)
):
    """Release a VLAN segment allocation"""
    return await AllocationService.release_vlan(request.cluster_name, request.site)

# Segment Management Routes
@router.get("/segments")
async def get_segments(
    site: Optional[str] = None,
    allocated: Optional[bool] = None,
    locked: Optional[bool] = None,
    type: Optional[str] = None,
):
    """Get segments with optional filters"""
    return await SegmentService.get_segments(site, allocated, locked, type)

@router.get("/segments/search")
async def search_segments(
    q: str, 
    site: Optional[str] = None, 
    allocated: Optional[bool] = None
):
    """Search segments by cluster name, EPG name, VLAN ID, description, or segment"""
    return await SegmentService.search_segments(q, site, allocated)

@router.post("/segments")
async def create_segment(
    segment: Segment,
    _: bool = Depends(require_auth)
):
    """Create a new segment"""
    return await SegmentService.create_segment(segment)

@router.get("/segments/{segment_id}")
async def get_segment(segment_id: str):
    """Get a single segment by ID"""
    return await SegmentService.get_segment_by_id(segment_id)

@router.put("/segments/{segment_id}")
async def update_segment(
    segment_id: str,
    segment: Segment,
    _: bool = Depends(require_auth)
):
    """Update a segment"""
    return await SegmentService.update_segment(segment_id, segment)

@router.put("/segments/{segment_id}/clusters")
async def update_segment_clusters(
    segment_id: str,
    request: dict,
    _: bool = Depends(require_auth)
):
    """Update cluster assignment for a segment (for shared segments)"""
    cluster_names = request.get("cluster_names", "")
    return await SegmentService.update_segment_clusters(segment_id, cluster_names)

@router.post("/segments/{segment_id}/unlock")
async def unlock_segment(
    segment_id: str,
    _: bool = Depends(require_auth)
):
    """Unlock a segment (locked -> available).

    New segments start locked (firewall rules not yet open) and are excluded
    from automatic VLAN allocation until unlocked. Intended to be called by
    the service responsible for opening firewall rules once it has done so.
    This is a one-way lifecycle transition — there is no endpoint to re-lock
    a segment.
    """
    return await SegmentService.unlock_segment(segment_id)

@router.delete("/segments/{segment_id}")
async def delete_segment(
    segment_id: str,
    _: bool = Depends(require_auth)
):
    """Delete a segment"""
    return await SegmentService.delete_segment(segment_id)

@router.post("/segments/bulk")
async def create_segments_bulk(
    segments: List[Segment],
    _: bool = Depends(require_auth)
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
    allocated: Optional[bool] = None
):
    """Export segments data as CSV"""
    return await ExportService.export_segments_csv(site=site, allocated=allocated)

@router.get("/export/segments/excel")
async def export_segments_excel(
    site: Optional[str] = None, 
    allocated: Optional[bool] = None
):
    """Export segments data as Excel"""
    return await ExportService.export_segments_excel(site=site, allocated=allocated)

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