from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field

SegmentType = Literal["MCE", "INVENTORY", "HC", "PXE"]


class Segment(BaseModel):
    type: SegmentType = Field(default="HC", description="Segment type", examples=["MCE"])
    site: str = Field(..., description="Site name (must be one of the configured sites)", examples=["site1"])
    vlan_id: int = Field(ge=1, le=4094, description="VLAN ID (1-4094)", examples=[100])
    epg_name: str = Field(..., description="Endpoint Group name", examples=["EPG_PROD_01"])
    segment: str = Field(..., description="Network segment in CIDR notation (must fall inside the site's configured pool)", examples=["192.10.1.0/24"])
    dhcp: bool = Field(default=True, description="Enable DHCP for this segment")
    cluster_name: Optional[str] = Field(default=None, description="Cluster name if allocated, None if available", examples=["cluster-prod-01"])
    allocated_at: Optional[datetime] = Field(default=None, description="Timestamp when segment was allocated")

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "type": "MCE",
                    "site": "site1",
                    "vlan_id": 100,
                    "epg_name": "EPG_PROD_01",
                    "segment": "192.168.1.0/24",
                    "dhcp": True
                }
            ]
        }
    }


class SegmentAllocationRequest(BaseModel):
    """Request for POST /api/segments/allocate.

    `type` is required — an allocator must never have to guess which kind of
    segment the caller wants. It also scopes the idempotency check, so one
    cluster can hold e.g. an MCE and an HC segment at the same site.
    """
    cluster_name: str = Field(..., description="Name of the cluster requesting allocation", examples=["cluster-prod-01"])
    site: str = Field(..., description="Site where the segment should be allocated", examples=["site1"])
    type: SegmentType = Field(..., description="Type of segment to allocate", examples=["MCE"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "cluster_name": "cluster-prod-01",
                    "site": "site1",
                    "type": "MCE"
                }
            ]
        }
    }


class SegmentAllocationResponse(BaseModel):
    vlan_id: int = Field(..., description="Allocated VLAN ID", examples=[100])
    cluster_name: str = Field(..., description="Cluster name", examples=["cluster-prod-01"])
    site: str = Field(..., description="Site name", examples=["site1"])
    type: SegmentType = Field(..., description="Type of the allocated segment", examples=["MCE"])
    segment: str = Field(..., description="Allocated network segment", examples=["192.168.1.0/24"])
    epg_name: str = Field(..., description="Endpoint Group name", examples=["EPG_PROD_01"])
    allocated_at: datetime = Field(..., description="Allocation timestamp")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "vlan_id": 100,
                    "cluster_name": "cluster-prod-01",
                    "site": "site1",
                    "type": "MCE",
                    "segment": "192.168.1.0/24",
                    "epg_name": "EPG_PROD_01",
                    "allocated_at": "2024-01-15T10:30:00Z"
                }
            ]
        }
    }


class SegmentDhcpUpdate(BaseModel):
    """Update request keyed by the segment's natural key (its CIDR).

    `dhcp` is the only in-place-editable segment field — identity fields
    (site, vlan_id, epg_name, segment) are immutable after creation, `type`
    changes only through the conversion endpoint (PUT /segments/type), and
    lifecycle fields are server-managed.
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    dhcp: bool = Field(..., description="New DHCP setting for this segment")

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "dhcp": True
                }
            ]
        }
    }


class SegmentTypeUpdate(BaseModel):
    """Request for PUT /api/segments/type — convert a segment to another type.

    `type` is the NEW type to set. `expected_type` is an optional
    compare-and-set guard: the current type the caller believes it is
    converting FROM. If the stored type matches neither `type` (already
    converted) nor `expected_type`, the conversion is refused (409) — another
    caller re-typed the segment first.
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    type: SegmentType = Field(..., description="New segment type to set", examples=["MCE"])
    expected_type: Optional[SegmentType] = Field(
        default=None,
        description="Compare-and-set guard: the current type being converted from; 409 if the stored type differs (unless it already equals the new type)",
        examples=["HC"],
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "type": "MCE",
                    "expected_type": "HC"
                }
            ]
        }
    }


class SegmentClustersUpdate(BaseModel):
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    cluster_name: Optional[str] = Field(
        default=None,
        description="Cluster name to assign (one segment belongs to at most one cluster); empty or omitted releases the segment",
        examples=["cluster-prod-01"],
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "cluster_name": "cluster-prod-01"
                }
            ]
        }
    }


class SegmentRelease(BaseModel):
    """Request for POST /api/segments/release, keyed by the segment CIDR.

    The CIDR is globally unique, so it alone identifies the allocation — no
    site, cluster_name or type is needed (or accepted).
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24"
                }
            ]
        }
    }
