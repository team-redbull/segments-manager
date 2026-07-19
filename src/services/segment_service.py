import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from ..database import STATUS_LOCKED, STATUS_AVAILABLE
from ..models.schemas import Segment
from ..utils.database_utils import DatabaseUtils
from ..utils.validators import Validators
from ..utils.error_handlers import handle_db_errors, retry_on_network_error
from ..utils.logging_decorators import log_operation_timing
from ..utils.time_utils import get_current_utc
from .workflow_client import trigger_segment_connectivity_workflow

logger = logging.getLogger(__name__)

class SegmentService:
    """Service class for segment management operations"""

    @staticmethod
    async def _validate_segment_data(segment: Segment) -> None:
        """Common validation for segment data"""
        Validators.validate_site(segment.site)
        Validators.validate_epg_name(segment.epg_name)
        Validators.validate_vlan_id(segment.vlan_id)

        Validators.validate_segment_format(segment.segment, segment.site)
        Validators.validate_subnet_mask(segment.segment)
        Validators.validate_no_reserved_ips(segment.segment)
        Validators.validate_network_broadcast_gateway(segment.segment)

        existing_segments = await DatabaseUtils.get_segments_with_filters()

        Validators.validate_ip_overlap(segment.segment, existing_segments)

        Validators.validate_vlan_name_uniqueness(
            site=segment.site,
            epg_name=segment.epg_name,
            vlan_id=segment.vlan_id,
            existing_segments=existing_segments
        )

    @staticmethod
    async def _get_segment_or_404(segment_value: str) -> Dict[str, Any]:
        """Resolve a segment document by its CIDR value (the natural key).

        The `segment` field is unique (unique index) and immutable, so it is
        the public identifier for all single-segment API operations — callers
        never need the internal Mongo ObjectId.
        """
        doc = await DatabaseUtils.get_segment_by_segment(segment_value.strip())
        if not doc:
            raise HTTPException(status_code=404, detail="Segment not found")
        return doc

    @staticmethod
    def _segment_to_dict(segment: Segment) -> Dict[str, Any]:
        """Convert segment object to dictionary"""
        return {
            "type": segment.type,
            "site": segment.site,
            "vlan_id": segment.vlan_id,
            "epg_name": segment.epg_name,
            "segment": segment.segment,
            "dhcp": segment.dhcp
        }

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("get_segments", threshold_ms=1000)
    async def get_segments(
        site: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get segments with optional filters"""
        segments = await DatabaseUtils.get_segments_with_filters(site, status, type)
        logger.debug(f"Retrieved {len(segments)} segments")
        return segments

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("search_segments", threshold_ms=1000)
    async def search_segments(
        search_query: str,
        site: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search segments by cluster name, EPG name, VLAN ID, or segment"""
        segments = await DatabaseUtils.search_segments(search_query, site, status)
        logger.debug(f"Found {len(segments)} matching segments for query '{search_query}'")
        return segments

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("create_segment", threshold_ms=2000)
    async def create_segment(segment: Segment) -> Dict[str, str]:
        """Create a new segment"""
        logger.info(f"Creating segment: site={segment.site}, vlan_id={segment.vlan_id}, epg={segment.epg_name}")

        await SegmentService._validate_segment_data(segment)

        if await DatabaseUtils.check_vlan_exists(segment.site, segment.vlan_id):
            raise HTTPException(
                status_code=400,
                detail=f"VLAN {segment.vlan_id} already exists at site '{segment.site}'"
            )

        segment_data = SegmentService._segment_to_dict(segment)
        segment_id = await DatabaseUtils.create_segment(segment_data)

        logger.info(f"Created segment with ID: {segment_id}")

        # Fire-and-return: kick off the (multi-day) segment-connectivity workflow and
        # respond as soon as it's been triggered, without waiting for it to
        # complete. Best-effort — never fails the segment creation itself.
        await trigger_segment_connectivity_workflow(segment.segment, segment.type)

        return {"message": "Segment created", "id": segment_id}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("get_segment_by_segment", threshold_ms=500)
    async def get_segment_by_segment(segment_value: str) -> Dict[str, Any]:
        """Get a single segment by its CIDR value (the natural key)"""
        segment = await SegmentService._get_segment_or_404(segment_value)
        logger.debug(f"Retrieved segment {segment_value}: site={segment.get('site')}, vlan_id={segment.get('vlan_id')}")
        return segment

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("update_segment_dhcp", threshold_ms=2000)
    async def update_segment_dhcp(segment_value: str, dhcp: bool) -> Dict[str, str]:
        """Update a segment's DHCP flag — the only mutable segment field.

        Everything else (site, vlan_id, epg_name, segment) is immutable after
        creation; lifecycle fields (status, cluster_name, ...) are managed by
        their own endpoints. Idempotent: setting the current value is a no-op.
        """
        existing_segment = await SegmentService._get_segment_or_404(segment_value)

        if existing_segment.get("dhcp") == dhcp:
            return {"message": "Segment already up to date"}

        success = await DatabaseUtils.update_segment_by_id(str(existing_segment["_id"]), {"dhcp": dhcp})
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update segment")

        logger.info(f"Updated segment {segment_value}: dhcp={dhcp}")
        return {"message": "Segment updated successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("update_segment_clusters", threshold_ms=2000)
    async def update_segment_clusters(segment_value: str, cluster_names: str) -> Dict[str, str]:
        """Update cluster assignment for a segment (for shared segments)"""
        from datetime import datetime, timezone
        logger.info(f"Updating cluster assignment for segment: {segment_value}")

        existing_segment = await SegmentService._get_segment_or_404(segment_value)
        segment_id = str(existing_segment["_id"])

        clean_cluster_names = cluster_names.strip() if cluster_names else None

        update_data = {}
        if clean_cluster_names:
            cluster_list = [name.strip() for name in clean_cluster_names.split(",")]
            validated_clusters = []
            for cluster in cluster_list:
                if cluster and cluster.replace("-", "").replace("_", "").isalnum():
                    validated_clusters.append(cluster)

            if validated_clusters:
                update_data["cluster_name"] = ",".join(validated_clusters)
                update_data["allocated_at"] = datetime.now(timezone.utc)
                update_data["released"] = False
                update_data["released_at"] = None
            else:
                update_data["cluster_name"] = None
                update_data["released"] = True
                update_data["released_at"] = datetime.now(timezone.utc)
        else:
            update_data["cluster_name"] = None
            update_data["released"] = True
            update_data["released_at"] = datetime.now(timezone.utc)

        success = await DatabaseUtils.update_segment_by_id(segment_id, update_data)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update segment clusters")

        logger.info(f"Updated cluster assignment for segment {segment_value}")
        return {"message": "Segment cluster assignment updated successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("set_segment_connectivity_requests", threshold_ms=2000)
    async def set_segment_connectivity_requests(
        segment_value: str, request_ids: List[int], submitted_at: Optional[datetime] = None
    ) -> Dict[str, str]:
        """Replace the pending segment-connectivity request ids displayed for a segment.

        Set by the segment-connectivity orchestrator while its firewall (open-rules)
        requests await approval; the UI shows the ids beside the segment's
        status, with `submitted_at` driving the "time since submit" header in
        the popover. An empty list clears the display (all requests completed).
        Idempotent: setting the current value is a no-op.
        """
        existing_segment = await SegmentService._get_segment_or_404(segment_value)

        new_value = request_ids or None
        new_submitted_at = submitted_at if new_value else None
        # A fresh submission (non-empty ids) supersedes any prior failure note:
        # re-triggering the workflow is exactly the operator's recovery path, so
        # clearing the "Workflow failed" note here keeps the row consistent.
        has_failure = existing_segment.get("segment_connectivity_failure") is not None
        clear_failure = bool(new_value) and has_failure
        if (
            existing_segment.get("segment_connectivity_requests") == new_value
            and existing_segment.get("segment_connectivity_requests_submitted_at") == new_submitted_at
            and not clear_failure
        ):
            return {"message": "Segment already up to date"}

        update: Dict[str, Any] = {
            "segment_connectivity_requests": new_value,
            "segment_connectivity_requests_submitted_at": new_submitted_at,
        }
        if clear_failure:
            update["segment_connectivity_failure"] = None
            update["segment_connectivity_failure_at"] = None

        success = await DatabaseUtils.update_segment_by_id(
            str(existing_segment["_id"]), update
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update segment")

        logger.info(f"Updated segment {segment_value}: segment_connectivity_requests={new_value}")
        return {"message": "Segment-connectivity requests updated"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("set_segment_connectivity_failure", threshold_ms=2000)
    async def set_segment_connectivity_failure(
        segment_value: str, message: str
    ) -> Dict[str, str]:
        """Record a terminal segment-connectivity-workflow failure for a segment.

        Set by the segment-connectivity orchestrator when its firewall (open-rules)
        workflow fails or is cancelled after submission. The UI shows a
        "Workflow failed" note beside the segment's status (the segment stays
        Locked — segment-connectivity was never established); `segment_connectivity_failure_at`
        drives the "N ago" header in the popover. Cleared automatically when a
        fresh set of request ids is published (see set_segment_connectivity_requests).
        Idempotent: re-recording the same message is a no-op.
        """
        existing_segment = await SegmentService._get_segment_or_404(segment_value)

        if existing_segment.get("segment_connectivity_failure") == message:
            return {"message": "Segment already up to date"}

        success = await DatabaseUtils.update_segment_by_id(
            str(existing_segment["_id"]),
            {
                "segment_connectivity_failure": message,
                "segment_connectivity_failure_at": get_current_utc(),
            },
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update segment")

        logger.info(f"Recorded segment-connectivity failure for segment {segment_value}")
        return {"message": "Segment-connectivity failure recorded"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("unlock_segment_by_segment", threshold_ms=2000)
    async def unlock_segment_by_segment(segment: str) -> Dict[str, str]:
        """Unlock a segment identified by its CIDR value (status "Locked" -> "Available").

        "Locked" is the initial status of every new segment (firewall rules
        not yet open), and segments are excluded from automatic VLAN
        allocation until unlocked. Intended for callers (e.g. the
        segment-connectivity orchestrator) that know the network value. This is a
        one-way lifecycle transition — segments cannot be re-locked via the
        API. Idempotent: unlocking a segment that is already "Available" (or
        "Allocated") is a no-op.
        """
        existing_segment = await SegmentService._get_segment_or_404(segment)

        if existing_segment.get("status") != STATUS_LOCKED:
            return {"message": "Segment already unlocked"}

        segment_id = str(existing_segment["_id"])
        success = await DatabaseUtils.update_segment_by_id(segment_id, {"status": STATUS_AVAILABLE})
        if not success:
            raise HTTPException(status_code=500, detail="Failed to unlock segment")

        logger.info(f"Segment {segment} unlocked (status: {STATUS_LOCKED} -> {STATUS_AVAILABLE})")
        return {"message": "Segment unlocked successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("delete_segment", threshold_ms=2000)
    async def delete_segment(segment_value: str) -> Dict[str, str]:
        """Delete a segment identified by its CIDR value"""
        segment = await SegmentService._get_segment_or_404(segment_value)

        Validators.validate_segment_not_allocated(segment)

        success = await DatabaseUtils.delete_segment_by_id(str(segment["_id"]))
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete segment")

        logger.info(f"Deleted segment {segment_value}")
        return {"message": "Segment deleted"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=2)
    @log_operation_timing("create_segments_bulk", threshold_ms=10000)
    async def create_segments_bulk(segments: List[Segment]) -> Dict[str, Any]:
        """Create multiple segments at once - fetches existing segments once for all validations"""
        logger.info(f"Bulk creating {len(segments)} segments")

        if not segments or len(segments) == 0:
            logger.warning("Bulk create called with empty segments list")
            raise HTTPException(
                status_code=400,
                detail="No valid segments found in CSV data. Please check the format: site,vlan_id,epg_name,segment,dhcp"
            )

        try:
            existing_segments = await DatabaseUtils.get_segments_with_filters()

            created = 0
            errors = []
            created_in_bulk = set()

            for idx, segment in enumerate(segments, start=1):
                try:
                    logger.debug(f"Processing segment {idx}/{len(segments)}: site={segment.site}, vlan_id={segment.vlan_id}")

                    # Check for duplicates within this bulk request (site+vlan scope)
                    segment_key = (segment.site, segment.vlan_id)
                    if segment_key in created_in_bulk:
                        error_msg = f"Duplicate entry: VLAN {segment.vlan_id} at site '{segment.site}' appears multiple times in CSV"
                        logger.warning(f"Row {idx}: {error_msg}")
                        errors.append(error_msg)
                        continue

                    await SegmentService._validate_segment_data(segment)

                    # Check if VLAN ID already exists at this site
                    vlan_exists = any(
                        s.get("site") == segment.site and s.get("vlan_id") == segment.vlan_id
                        for s in existing_segments
                    )
                    if vlan_exists:
                        error_msg = f"VLAN {segment.vlan_id} already exists at site '{segment.site}'"
                        logger.warning(f"Row {idx}: {error_msg}")
                        errors.append(error_msg)
                        continue

                    segment_data = SegmentService._segment_to_dict(segment)
                    new_segment = await DatabaseUtils.create_segment(segment_data)

                    # Best-effort — never fails this row's creation.
                    await trigger_segment_connectivity_workflow(segment.segment, segment.type)

                    created_in_bulk.add(segment_key)
                    existing_segments.append(new_segment if isinstance(new_segment, dict) else segment_data)
                    created += 1
                    logger.debug(f"Successfully created segment {idx}: site={segment.site}, vlan_id={segment.vlan_id}")

                except HTTPException as e:
                    error_msg = f"Row {idx} (Site {segment.site}, VLAN {segment.vlan_id}): {e.detail}"
                    logger.error(f"Validation error for segment {idx}: {error_msg}", exc_info=True)
                    errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Row {idx} (Site {segment.site}, VLAN {segment.vlan_id}): {str(e)}"
                    logger.error(f"Error creating segment {idx}: {error_msg}", exc_info=True)
                    errors.append(error_msg)

            logger.info(f"Bulk creation complete: {created} created, {len(errors)} errors")

            return {
                "message": f"Created {created} segments",
                "created": created,
                "errors": errors if errors else None
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error in bulk creation: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
