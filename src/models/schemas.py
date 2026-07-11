from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field

SegmentType = Literal["MCE", "INVENTORY", "HC", "PXE"]


class Segment(BaseModel):
    type: SegmentType = Field(default="HC", description="Segment type", examples=["MCE"])
    site: str = Field(..., description="Site name (must be one of the configured sites)", examples=["site1"])
    vlan_id: int = Field(ge=1, le=4094, description="VLAN ID (1-4094)", examples=[100])
    epg_name: str = Field(..., description="Endpoint Group name", examples=["EPG_PROD_01"])
    segment: str = Field(..., description="Network segment in CIDR notation (must match site IP prefix)", examples=["192.168.1.0/24"])
    dhcp: bool = Field(default=True, description="Enable DHCP for this segment")
    cluster_name: Optional[str] = Field(default=None, description="Cluster name if allocated, None if available", examples=["cluster-prod-01"])
    allocated_at: Optional[datetime] = Field(default=None, description="Timestamp when segment was allocated")
    released: bool = Field(default=False, description="Whether segment was previously released")
    released_at: Optional[datetime] = Field(default=None, description="Timestamp when segment was released")

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
    cluster_name: str = Field(..., description="Name of the cluster requesting allocation", examples=["cluster-prod-01"])
    site: str = Field(..., description="Site where the segment should be allocated", examples=["site1"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "cluster_name": "cluster-prod-01",
                    "site": "site1"
                }
            ]
        }
    }


class SegmentAllocationResponse(BaseModel):
    vlan_id: int = Field(..., description="Allocated VLAN ID", examples=[100])
    cluster_name: str = Field(..., description="Cluster name", examples=["cluster-prod-01"])
    site: str = Field(..., description="Site name", examples=["site1"])
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
                    "segment": "192.168.1.0/24",
                    "epg_name": "EPG_PROD_01",
                    "allocated_at": "2024-01-15T10:30:00Z"
                }
            ]
        }
    }


class SegmentRelease(BaseModel):
    cluster_name: str = Field(..., description="Name of the cluster to release", examples=["cluster-prod-01"])
    site: str = Field(..., description="Site where cluster is allocated", examples=["site1"])

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "cluster_name": "cluster-prod-01",
                    "site": "site1"
                }
            ]
        }
    }
