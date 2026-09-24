from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, model_validator

SegmentType = Literal["MCE", "INVENTORY", "HC", "PXE"]


class Segment(BaseModel):
    """A segment definition, as created (POST /api/segments and /bulk).

    There is no `type`: a segment is not born as any particular kind. The type
    is ALLOCATION state, like cluster_name — POST /api/segments/allocate stamps
    the requested type onto the segment it hands out, and release clears it
    again. Sending one here is rejected (extra="forbid").
    """
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
    segment the caller wants. Available segments carry no type, so it does not
    narrow the pool: any Available segment at the site is handed out and
    becomes this type. It also scopes the idempotency check, so one cluster can
    hold e.g. an MCE and an HC segment at the same site.
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
    type: SegmentType = Field(..., description="Type the segment was allocated as", examples=["MCE"])
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
    (site, vlan_id, epg_name, segment) are immutable after creation, and
    lifecycle fields (status, cluster_name, type, ...) are server-managed.
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


class SegmentClustersUpdate(BaseModel):
    """Request for PUT /api/segments/clusters — a manual allocation edit.

    Assigning a cluster allocates the segment, so it needs the `type` to
    allocate it AS, exactly like POST /api/segments/allocate: an Allocated
    segment always has a type and an Available one never does. Releasing (empty
    or omitted cluster_name) clears the type, so sending one there is refused
    rather than silently dropped.
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    cluster_name: Optional[str] = Field(
        default=None,
        description="Cluster name to assign (one segment belongs to at most one cluster); empty or omitted releases the segment",
        examples=["cluster-prod-01"],
    )
    type: Optional[SegmentType] = Field(
        default=None,
        description="Type to allocate the segment as — required with a cluster_name, forbidden without one",
        examples=["HC"],
    )

    @model_validator(mode="after")
    def _type_goes_with_cluster(self) -> "SegmentClustersUpdate":
        assigning = bool(self.cluster_name and self.cluster_name.strip())
        if assigning and self.type is None:
            raise ValueError("type is required when assigning a cluster_name")
        if not assigning and self.type is not None:
            raise ValueError("type is only accepted with a cluster_name — releasing clears it")
        return self

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "cluster_name": "cluster-prod-01",
                    "type": "HC"
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
