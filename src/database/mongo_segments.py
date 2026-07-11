"""
MongoDB Segment Operations

Domain-level async functions for segment CRUD and allocation.
Allocation is atomic via find_one_and_update; segments are scoped
per-site.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .mongo_client import get_segments_collection
from .mongo_utils import _doc_to_segment, _to_object_id
from .cache import (
    get_cached, set_cache, invalidate_cache,
    get_inflight_request, set_inflight_request, remove_inflight_request,
    CACHE_KEY_SEGMENTS, CACHE_TTL_SHORT,
)

logger = logging.getLogger(__name__)

# Segment lifecycle statuses: Locked -> Available -> Allocated -> Available.
# Locking is one-way — there is no API surface that re-locks a segment.
STATUS_LOCKED = "Locked"
STATUS_AVAILABLE = "Available"
STATUS_ALLOCATED = "Allocated"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _segment_matches(
    segment: Dict[str, Any],
    site: Optional[str],
    vlan_id: Optional[int],
    cluster_name: Optional[str],
    status: Optional[str] = None,
    type: Optional[str] = None,
) -> bool:
    """Return True if segment satisfies all non-None filter criteria."""
    if site is not None and segment.get("site", "").lower() != site.lower():
        return False
    if vlan_id is not None and segment.get("vlan_id") != vlan_id:
        return False
    if cluster_name is not None and segment.get("cluster_name") != cluster_name:
        return False
    if status is not None and str(segment.get("status", "")).lower() != status.lower():
        return False
    if type is not None and str(segment.get("type", "")).lower() != type.lower():
        return False
    return True


async def _fetch_all_segments() -> List[Dict[str, Any]]:
    """Fetch all segments from MongoDB, using the cache when available."""
    cached = get_cached(CACHE_KEY_SEGMENTS)
    if cached is not None:
        return cached

    # In-flight deduplication — prevent concurrent duplicate fetches
    inflight = get_inflight_request(CACHE_KEY_SEGMENTS)
    if inflight is not None:
        try:
            return await inflight
        except Exception:
            pass

    async def _do_fetch():
        col = get_segments_collection()
        docs = await col.find({}).to_list(length=None)
        segments = [_doc_to_segment(d) for d in docs]
        set_cache(CACHE_KEY_SEGMENTS, segments, ttl=CACHE_TTL_SHORT)
        return segments

    task = asyncio.create_task(_do_fetch())
    set_inflight_request(CACHE_KEY_SEGMENTS, task)
    try:
        result = await task
        return result
    finally:
        remove_inflight_request(CACHE_KEY_SEGMENTS)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def get_segments(
    site: Optional[str] = None,
    vlan_id: Optional[int] = None,
    cluster_name: Optional[str] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return segments matching all provided filter criteria."""
    all_segments = await _fetch_all_segments()
    return [
        s for s in all_segments
        if _segment_matches(s, site, vlan_id, cluster_name, status, type)
    ]


async def get_segment_by_id(segment_id: str) -> Optional[Dict[str, Any]]:
    """Return a single segment by its ID, or None if not found."""
    oid = _to_object_id(segment_id)
    col = get_segments_collection()
    doc = await col.find_one({"_id": oid})
    return _doc_to_segment(doc) if doc else None


async def get_segment_by_segment(segment: str) -> Optional[Dict[str, Any]]:
    """Return a single segment by its CIDR value (unique index), or None if not found."""
    col = get_segments_collection()
    doc = await col.find_one({"segment": segment})
    return _doc_to_segment(doc) if doc else None


async def create_segment(document: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new segment document and return the created segment."""
    col = get_segments_collection()
    doc = {k: v for k, v in document.items() if k != "_id"}
    doc.setdefault("type", "HC")
    doc.setdefault("dhcp", True)
    doc.setdefault("cluster_name", None)
    doc.setdefault("allocated_at", None)
    doc.setdefault("released", False)
    doc.setdefault("released_at", None)
    # New segments start in the "Locked" lifecycle status (firewall rules not
    # yet open) until an external service unlocks them via
    # POST /segments/unlock (or /segments/{id}/unlock). Lifecycle:
    # Locked -> Available -> Allocated -> Available.
    doc.setdefault("status", STATUS_LOCKED)

    result = await col.insert_one(doc)
    invalidate_cache(CACHE_KEY_SEGMENTS)
    created = await col.find_one({"_id": result.inserted_id})
    return _doc_to_segment(created)


async def update_segment(segment_id: str, updates: Dict[str, Any]) -> bool:
    """Apply a partial update to a segment. Returns True if a document was modified."""
    oid = _to_object_id(segment_id)
    # Never allow overwriting _id
    safe_updates = {k: v for k, v in updates.items() if k != "_id"}
    col = get_segments_collection()
    result = await col.update_one({"_id": oid}, {"$set": safe_updates})
    if result.modified_count > 0:
        invalidate_cache(CACHE_KEY_SEGMENTS)
        return True
    return False


async def delete_segment(segment_id: str) -> bool:
    """Delete a segment by ID. Returns True if a document was deleted."""
    oid = _to_object_id(segment_id)
    col = get_segments_collection()
    result = await col.delete_one({"_id": oid})
    if result.deleted_count > 0:
        invalidate_cache(CACHE_KEY_SEGMENTS)
        return True
    return False


async def allocate_segment(
    site: str,
    cluster_name: str,
    sort_by_vlan_id: bool = True,
) -> Optional[Dict[str, Any]]:
    """Atomically find an available segment for the given site and mark it allocated.

    Uses find_one_and_update for true atomicity — unlike the previous two-step
    find-then-update approach, concurrent callers cannot receive the same segment.
    """
    from pymongo import ReturnDocument

    col = get_segments_collection()

    query = {
        "site": {"$regex": f"^{site}$", "$options": "i"},
        "status": STATUS_AVAILABLE,
    }
    sort = [("vlan_id", 1)] if sort_by_vlan_id else None
    update = {
        "$set": {
            "status": STATUS_ALLOCATED,
            "cluster_name": cluster_name,
            "allocated_at": datetime.now(timezone.utc),
            "released": False,
            "released_at": None,
        }
    }

    doc = await col.find_one_and_update(
        query,
        update,
        sort=sort,
        return_document=ReturnDocument.AFTER,
    )
    if doc:
        invalidate_cache(CACHE_KEY_SEGMENTS)
        return _doc_to_segment(doc)
    return None
