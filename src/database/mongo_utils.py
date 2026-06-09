"""
MongoDB Utilities

Document conversion helpers and ObjectId handling.
"""

from typing import Any, Dict
from bson import ObjectId
from fastapi import HTTPException


def _doc_to_segment(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a MongoDB document to the canonical segment dict.

    Converts _id from ObjectId to str so callers always receive strings.
    """
    result = dict(doc)
    result["_id"] = str(result["_id"])
    return result


def _to_object_id(segment_id: str) -> ObjectId:
    """Convert a segment ID string to a MongoDB ObjectId.

    Raises HTTP 400 on malformed input so the error surfaces cleanly at the API layer.
    """
    try:
        return ObjectId(segment_id)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid segment ID format: '{segment_id}'")
