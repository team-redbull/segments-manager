"""Input field validators for Segments Manager.

Handles validation of basic input fields like site, VLAN ID, EPG name, and cluster name.
"""

import logging
import re
from fastapi import HTTPException

from ...config.settings import SITES

logger = logging.getLogger(__name__)


class InputValidators:
    """Validators for basic input fields"""

    @staticmethod
    def validate_site(site: str) -> None:
        """Validate if site is in configured sites (case-insensitive)"""
        logger.debug(f"Validating site: {site}")
        # Normalize to lowercase for case-insensitive comparison
        site_lower = site.lower()
        sites_lower = [s.lower() for s in SITES]
        if site_lower not in sites_lower:
            logger.warning(f"Invalid site: {site}, valid sites: {SITES}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid site. Must be one of: {SITES}"
            )

    @staticmethod
    def validate_epg_name(epg_name: str) -> None:
        """Validate that EPG name is not empty or whitespace only"""
        logger.debug(f"Validating EPG name: '{epg_name}'")

        if not epg_name or not epg_name.strip():
            logger.warning("Invalid EPG name: empty or whitespace only")
            raise HTTPException(
                status_code=400,
                detail="EPG name cannot be empty or contain only whitespace"
            )

        if len(epg_name) > 64:
            logger.warning(f"EPG name too long: {len(epg_name)} characters")
            raise HTTPException(
                status_code=400,
                detail=f"EPG name too long (max 64 characters, got {len(epg_name)})"
            )

        # Check for invalid characters (restrict to network-safe VLAN name chars)
        if not re.match(r'^[a-zA-Z0-9_\-\./]+$', epg_name):
            logger.warning(f"EPG name contains invalid characters: '{epg_name}'")
            raise HTTPException(
                status_code=400,
                detail="EPG name can only contain letters, numbers, underscores, hyphens, dots, and forward slashes"
            )

    @staticmethod
    def validate_vlan_id(vlan_id: int) -> None:
        """Validate VLAN ID is within valid range"""
        logger.debug(f"Validating VLAN ID: {vlan_id}")

        if not isinstance(vlan_id, int):
            raise HTTPException(
                status_code=400,
                detail=f"VLAN ID must be an integer, got {type(vlan_id).__name__}"
            )

        if vlan_id < 1 or vlan_id > 4094:
            logger.warning(f"VLAN ID out of range: {vlan_id}")
            raise HTTPException(
                status_code=400,
                detail=f"VLAN ID must be between 1 and 4094 (got {vlan_id})"
            )

        # Reserved VLANs
        if vlan_id == 1:
            logger.warning("VLAN 1 is reserved (default VLAN)")

    @staticmethod
    def validate_cluster_name(cluster_name: str) -> None:
        """Validate cluster name format"""
        logger.debug(f"Validating cluster name: '{cluster_name}'")

        if not cluster_name or not cluster_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Cluster name cannot be empty or contain only whitespace"
            )

        if len(cluster_name) > 100:
            logger.warning(f"Cluster name too long: {len(cluster_name)} characters")
            raise HTTPException(
                status_code=400,
                detail=f"Cluster name too long (max 100 characters, got {len(cluster_name)})"
            )

        # Allow letters, numbers, hyphens, underscores, dots (for FQDNs)
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', cluster_name):
            logger.warning(f"Cluster name contains invalid characters: '{cluster_name}'")
            raise HTTPException(
                status_code=400,
                detail="Cluster name can only contain letters, numbers, hyphens, underscores, and dots"
            )
