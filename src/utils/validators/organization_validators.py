"""Organization and business logic validators for Segments Manager."""

import logging
from typing import Dict, Any, List, Optional
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class OrganizationValidators:
    """Validators for business logic and organizational rules."""

    @staticmethod
    def validate_segment_not_allocated(segment: Dict[str, Any]) -> None:
        """Validate that a segment is not currently allocated."""
        if segment.get("cluster_name") and not segment.get("released", False):
            raise HTTPException(
                status_code=400,
                detail="Cannot delete allocated segment"
            )

    @staticmethod
    def validate_vlan_name_uniqueness(
        site: str,
        epg_name: str,
        vlan_id: int,
        existing_segments: List[Dict[str, Any]],
        exclude_id: Optional[str] = None,
    ) -> None:
        """Validate that EPG name + VLAN ID combination is unique per site.

        The same VLAN ID can exist at different sites. Within the same site
        an EPG name must always map to the same VLAN ID.

        Args:
            site: Site name (e.g., "site1")
            epg_name: Endpoint Group name
            vlan_id: VLAN ID (1-4094)
            existing_segments: Segments to check against
            exclude_id: Segment ID to skip (for update operations)
        """
        for segment in existing_segments:
            if exclude_id and str(segment.get("_id")) == str(exclude_id):
                continue

            # Only enforce uniqueness within the same site
            if segment.get("site", "").lower() != site.lower():
                continue

            if (segment.get("epg_name") == epg_name and
                    segment.get("vlan_id") != vlan_id):
                logger.warning(
                    f"EPG name conflict at {site}: '{epg_name}' already used with VLAN {segment.get('vlan_id')}"
                )
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"EPG name '{epg_name}' is already used with VLAN {segment.get('vlan_id')} "
                        f"at site '{site}'. Cannot assign it to VLAN {vlan_id}."
                    )
                )

        logger.debug(f"EPG name uniqueness validation passed for '{epg_name}' at {site}")
