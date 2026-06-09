"""Network validation for IP segments and subnet masks.

Handles all network-related validations including IP format, subnet masks,
reserved IP ranges, overlap detection, and network/broadcast/gateway checks.
"""

import logging
import ipaddress
from typing import List, Dict, Any
from fastapi import HTTPException

from ...config.settings import get_site_prefix

logger = logging.getLogger(__name__)


class NetworkValidators:
    """Validators for network and IP-related fields"""

    @staticmethod
    def validate_segment_format(segment: str, site: str) -> None:
        """Validate that segment IP matches the site's IP prefix and is proper network format.

        Args:
            segment: IP network in CIDR format (e.g., "192.168.1.0/24")
            site: Site name (e.g., "Site1")

        Raises:
            HTTPException: If segment format is invalid or doesn't match expected prefix
        """
        logger.debug(f"Validating segment format: '{segment}' for site '{site}'")
        expected_prefix = get_site_prefix(site)

        if expected_prefix is None:
            logger.error(f"No IP prefix configured for site '{site}'")
            raise HTTPException(
                status_code=400,
                detail=f"Site '{site}' is not configured. "
                       f"Please ensure the site is listed in SITES and has a corresponding entry in SITE_PREFIXES."
            )

        try:
            # First validate that the segment includes explicit subnet mask
            if '/' not in segment:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid network format. Segment must include subnet mask (e.g., '{segment}/24')"
                )

            # Then validate that the segment is in proper network format
            try:
                ipaddress.ip_network(segment, strict=True)
            except ipaddress.AddressValueError:
                # If strict parsing fails, get the correct network address
                network_loose = ipaddress.ip_network(segment, strict=False)
                correct_format = str(network_loose)
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid network format. Use network address '{correct_format}' instead of '{segment}'"
                )

            # Parse the network segment for site prefix validation
            network = ipaddress.ip_network(segment, strict=False)
            first_octet = str(network.network_address).split('.')[0]

            if first_octet != expected_prefix:
                logger.warning(f"IP prefix mismatch for site '{site}': expected '{expected_prefix}', got '{first_octet}'")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid IP prefix for site '{site}'. "
                           f"Expected to start with '{expected_prefix}', got '{first_octet}'"
                )

        except ipaddress.AddressValueError:
            logger.warning(f"Invalid IP network format: {segment}")
            raise HTTPException(status_code=400, detail="Invalid IP network format")

    @staticmethod
    def validate_subnet_mask(segment: str) -> None:
        """Validate subnet mask is within reasonable range"""
        try:
            network = ipaddress.ip_network(segment, strict=False)
            prefix_len = network.prefixlen

            # Typical datacenter subnets: /16 to /31
            # /32 is a host route, not a network
            # /8 to /15 are too large for typical allocations
            if prefix_len < 16 or prefix_len > 31:
                logger.warning(f"Unusual subnet mask: /{prefix_len}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Subnet mask /{prefix_len} is outside supported range (/16 to /31). "
                           f"Use /16-/24 for large networks, /25-/29 for smaller subnets, "
                           f"or /30-/31 for point-to-point links (RFC 3021)."
                )

            logger.debug(f"Subnet mask validation passed: /{prefix_len}")
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid network format: {str(e)}"
            )

    @staticmethod
    def validate_no_reserved_ips(segment: str) -> None:
        """Validate that segment doesn't use reserved/special IP ranges"""
        try:
            network = ipaddress.ip_network(segment, strict=False)

            first_octet = int(str(network.network_address).split('.')[0])

            if first_octet == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot use 0.0.0.0/8 network (current network identifier)"
                )

            if first_octet == 127:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot use 127.0.0.0/8 network (loopback addresses)"
                )

            if first_octet == 169 and str(network.network_address).startswith("169.254"):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot use 169.254.0.0/16 network (link-local addresses)"
                )

            if first_octet >= 224:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot use {first_octet}.0.0.0/8 network (multicast/reserved range)"
                )

            logger.debug(f"Reserved IP validation passed for {segment}")

        except ipaddress.AddressValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid IP network: {str(e)}"
            )

    @staticmethod
    def validate_ip_overlap(new_segment: str, existing_segments: List[Dict[str, Any]]) -> None:
        """
        Validate that a new segment doesn't overlap with existing segments

        Args:
            new_segment: New IP network to validate (e.g., "192.168.1.0/24")
            existing_segments: List of existing segment dictionaries with 'segment' field

        Raises:
            HTTPException: If overlap detected
        """
        try:
            new_network = ipaddress.ip_network(new_segment, strict=False)

            for existing in existing_segments:
                if not existing.get("segment"):
                    continue

                try:
                    existing_network = ipaddress.ip_network(existing["segment"], strict=False)

                    if new_network.overlaps(existing_network):
                        logger.warning(f"IP overlap detected: {new_segment} overlaps with {existing['segment']}")
                        raise HTTPException(
                            status_code=400,
                            detail=f"IP segment {new_segment} overlaps with existing segment {existing['segment']} "
                                   f"(Site: {existing.get('site')}, VLAN: {existing.get('vlan_id')})"
                        )

                except ValueError:
                    logger.warning(f"Skipping invalid existing segment: {existing.get('segment')}")
                    continue

            logger.debug(f"No IP overlap detected for {new_segment}")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid IP network format: {str(e)}"
            )

    @staticmethod
    def validate_network_broadcast_gateway(segment: str) -> None:
        """
        Validate network has sufficient usable IPs (not just network and broadcast)

        A /31 network has only 2 IPs (both usable in point-to-point)
        A /30 network has 4 IPs (2 usable, 2 for network/broadcast)
        Warn about very small networks
        """
        try:
            network = ipaddress.ip_network(segment, strict=False)
            num_addresses = network.num_addresses

            if num_addresses < 2:
                logger.warning(f"Network too small: {segment} has only {num_addresses} addresses")
                raise HTTPException(
                    status_code=400,
                    detail=f"Network {segment} has fewer than 2 addresses and cannot be used as a subnet."
                )

            logger.debug(f"Network validation passed: {segment} has {num_addresses} addresses")

        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid network format: {str(e)}"
            )
