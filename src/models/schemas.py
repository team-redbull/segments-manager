from typing import List, Optional, Literal
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


class SegmentUnlock(BaseModel):
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


class SegmentConnectivityRequestsUpdate(BaseModel):
    """Pending segment-connectivity (firewall) request ids to display for a segment.

    Sent by the segment-connectivity orchestrator while its firewall requests await
    approval; the UI shows the ids beside the segment's status. An empty list
    clears the display (all requests completed).
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    request_ids: List[int] = Field(..., description="Pending segment-connectivity request ids; an empty list clears the display", examples=[[123456, 654321]])
    submitted_at: Optional[datetime] = Field(default=None, description="When these requests were originally submitted; drives the \"time since submit\" header in the UI popover. Ignored/cleared when request_ids is empty.", examples=["2024-01-15T10:30:00Z"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "request_ids": [123456, 654321],
                    "submitted_at": "2024-01-15T10:30:00Z"
                }
            ]
        }
    }


class SegmentConnectivityFailure(BaseModel):
    """A terminal segment-connectivity-workflow failure to display for a segment.

    Sent by the segment-connectivity orchestrator when its workflow fails or is
    cancelled after submission. The UI shows a "Workflow failed" note beside
    the segment's status; the segment stays Locked (segment-connectivity was never
    established). Cleared automatically when a fresh set of request ids is
    published for the segment (a new run supersedes the stale failure).
    """
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    message: str = Field(..., min_length=1, description="Human-readable failure reason shown in the UI popover (includes any orphaned request ids)", examples=["Segment-connectivity workflow failed: no same-site MCE segments found (orphaned next request ids: [496252, 825197])"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "message": "Segment-connectivity workflow failed: no same-site MCE segments found"
                }
            ]
        }
    }


class SegmentDhcpUpdate(BaseModel):
    """Update request keyed by the segment's natural key (its CIDR).

    `dhcp` is the only mutable segment field — everything else (site, vlan_id,
    epg_name, segment) is immutable after creation, and lifecycle fields are
    server-managed.
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
    segment: str = Field(..., description="Network segment in CIDR notation (unique per segment)", examples=["192.168.1.0/24"])
    cluster_names: Optional[str] = Field(
        default=None,
        description="Comma-separated cluster names to assign; empty or omitted releases the segment",
        examples=["cluster-prod-01,cluster-prod-02"],
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "segment": "192.168.1.0/24",
                    "cluster_names": "cluster-prod-01,cluster-prod-02"
                }
            ]
        }
    }


class SegmentRelease(BaseModel):
    """Request for POST /api/segments/release, keyed by the segment CIDR.

    The CIDR is globally unique, so it alone identifies the allocation — no
    site, cluster_name or type is needed (or accepted). Releasing a shared
    segment frees it from *all* its clusters; use PUT /api/segments/clusters
    to drop a single cluster from a shared list.
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
