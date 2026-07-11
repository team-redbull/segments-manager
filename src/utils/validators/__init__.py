"""Validators module for Segments Manager.

This module provides a unified Validators class that aggregates all validation methods
from specialized validator modules. This maintains backward compatibility with existing code.

Module structure:
- input_validators.py: Site, VLAN ID, EPG name, cluster name
- network_validators.py: IP format, subnet masks, reserved IPs, overlap detection
- organization_validators.py: Allocation state, uniqueness
"""

from .input_validators import InputValidators
from .network_validators import NetworkValidators
from .organization_validators import OrganizationValidators


class Validators:
    """Unified validators class - aggregates all validation methods for backward compatibility"""

    # Input validation methods
    validate_site = staticmethod(InputValidators.validate_site)
    validate_object_id = staticmethod(InputValidators.validate_object_id)
    validate_epg_name = staticmethod(InputValidators.validate_epg_name)
    validate_vlan_id = staticmethod(InputValidators.validate_vlan_id)
    validate_cluster_name = staticmethod(InputValidators.validate_cluster_name)

    # Network validation methods
    validate_segment_format = staticmethod(NetworkValidators.validate_segment_format)
    validate_subnet_mask = staticmethod(NetworkValidators.validate_subnet_mask)
    validate_no_reserved_ips = staticmethod(NetworkValidators.validate_no_reserved_ips)
    validate_ip_overlap = staticmethod(NetworkValidators.validate_ip_overlap)
    validate_network_broadcast_gateway = staticmethod(NetworkValidators.validate_network_broadcast_gateway)

    # Organization/business validation methods
    validate_segment_not_allocated = staticmethod(OrganizationValidators.validate_segment_not_allocated)
    validate_vlan_name_uniqueness = staticmethod(OrganizationValidators.validate_vlan_name_uniqueness)


# Export all classes for direct import if needed
__all__ = [
    "Validators",
    "InputValidators",
    "NetworkValidators",
    "OrganizationValidators",
]
