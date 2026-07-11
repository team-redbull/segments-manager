import logging
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from ..models.schemas import Segment
from ..utils.database_utils import DatabaseUtils
from ..utils.validators import Validators
from ..utils.error_handlers import handle_db_errors, retry_on_network_error
from ..utils.logging_decorators import log_operation_timing

logger = logging.getLogger(__name__)

class SegmentService:
    """Service class for segment management operations"""

    @staticmethod
    async def _validate_segment_data(segment: Segment, exclude_id: str = None) -> None:
        """Common validation for segment data"""
        Validators.validate_site(segment.site)
        Validators.validate_epg_name(segment.epg_name)
        Validators.validate_vlan_id(segment.vlan_id)

        Validators.validate_segment_format(segment.segment, segment.site)
        Validators.validate_subnet_mask(segment.segment)
        Validators.validate_no_reserved_ips(segment.segment)
        Validators.validate_network_broadcast_gateway(segment.segment)

        existing_segments = await DatabaseUtils.get_segments_with_filters()
        if exclude_id:
            existing_segments = [s for s in existing_segments if str(s.get("_id")) != str(exclude_id)]

        Validators.validate_ip_overlap(segment.segment, existing_segments)

        Validators.validate_vlan_name_uniqueness(
            site=segment.site,
            epg_name=segment.epg_name,
            vlan_id=segment.vlan_id,
            existing_segments=existing_segments,
            exclude_id=exclude_id
        )

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
        allocated: Optional[bool] = None,
        locked: Optional[bool] = None,
        type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get segments with optional filters"""
        segments = await DatabaseUtils.get_segments_with_filters(site, allocated, locked, type)
        logger.debug(f"Retrieved {len(segments)} segments")
        return segments

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("search_segments", threshold_ms=1000)
    async def search_segments(
        search_query: str,
        site: Optional[str] = None,
        allocated: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Search segments by cluster name, EPG name, VLAN ID, or segment"""
        segments = await DatabaseUtils.search_segments(search_query, site, allocated)
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
        return {"message": "Segment created", "id": segment_id}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("get_segment_by_id", threshold_ms=500)
    async def get_segment_by_id(segment_id: str) -> Dict[str, Any]:
        """Get a single segment by ID"""
        Validators.validate_object_id(segment_id)

        segment = await DatabaseUtils.get_segment_by_id(segment_id)
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        if not isinstance(segment["_id"], str):
            segment["_id"] = str(segment["_id"])

        logger.debug(f"Retrieved segment {segment_id}: site={segment.get('site')}, vlan_id={segment.get('vlan_id')}")
        return segment

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("update_segment", threshold_ms=2000)
    async def update_segment(segment_id: str, updated_segment: Segment) -> Dict[str, str]:
        """Update a segment"""
        Validators.validate_object_id(segment_id)

        await SegmentService._validate_segment_data(updated_segment, exclude_id=segment_id)

        existing_segment = await DatabaseUtils.get_segment_by_id(segment_id)
        if not existing_segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        # VLAN ID is immutable
        if existing_segment["vlan_id"] != updated_segment.vlan_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "vlan_id_immutable",
                    "message": "VLAN ID cannot be changed after creation",
                    "current_vlan_id": existing_segment["vlan_id"],
                    "attempted_vlan_id": updated_segment.vlan_id,
                    "suggestion": "Create a new segment with the desired VLAN ID and delete the old one if needed"
                }
            )

        # Check if site change would conflict with existing VLAN at target site
        if existing_segment["site"] != updated_segment.site:
            if await DatabaseUtils.check_vlan_exists_excluding_id(updated_segment.site, updated_segment.vlan_id, segment_id):
                raise HTTPException(
                    status_code=400,
                    detail=f"VLAN {updated_segment.vlan_id} already exists at site '{updated_segment.site}'"
                )

        update_data = SegmentService._segment_to_dict(updated_segment)
        success = await DatabaseUtils.update_segment_by_id(segment_id, update_data)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update segment")

        logger.info(f"Updated segment {segment_id}")
        return {"message": "Segment updated successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("update_segment_clusters", threshold_ms=2000)
    async def update_segment_clusters(segment_id: str, cluster_names: str) -> Dict[str, str]:
        """Update cluster assignment for a segment (for shared segments)"""
        from datetime import datetime, timezone
        logger.info(f"Updating cluster assignment for segment: {segment_id}")

        Validators.validate_object_id(segment_id)

        existing_segment = await DatabaseUtils.get_segment_by_id(segment_id)
        if not existing_segment:
            logger.warning(f"Segment not found: {segment_id}")
            raise HTTPException(status_code=404, detail="Segment not found")

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

        logger.info(f"Updated cluster assignment for segment {segment_id}")
        return {"message": "Segment cluster assignment updated successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("unlock_segment", threshold_ms=2000)
    async def unlock_segment(segment_id: str) -> Dict[str, str]:
        """Unlock a segment (locked -> available).

        Locked is the initial state of every new segment (firewall rules not
        yet open), and segments are excluded from automatic VLAN allocation
        while locked. This is a one-way lifecycle transition — segments
        cannot be re-locked via the API. Idempotent: unlocking an
        already-unlocked segment is a no-op.
        """
        Validators.validate_object_id(segment_id)

        existing_segment = await DatabaseUtils.get_segment_by_id(segment_id)
        if not existing_segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        if not bool(existing_segment.get("locked", False)):
            return {"message": "Segment already unlocked"}

        success = await DatabaseUtils.update_segment_by_id(segment_id, {"locked": False})
        if not success:
            raise HTTPException(status_code=500, detail="Failed to unlock segment")

        logger.info(f"Segment {segment_id} unlocked")
        return {"message": "Segment unlocked successfully"}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("delete_segment", threshold_ms=2000)
    async def delete_segment(segment_id: str) -> Dict[str, str]:
        """Delete a segment"""
        Validators.validate_object_id(segment_id)

        segment = await DatabaseUtils.get_segment_by_id(segment_id)
        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        Validators.validate_segment_not_allocated(segment)

        success = await DatabaseUtils.delete_segment_by_id(segment_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete segment")

        logger.info(f"Deleted segment {segment_id}")
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
