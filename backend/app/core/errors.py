"""
Unified error response schema for the API.
"""

from pydantic import BaseModel
from typing import Optional, Any


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[Any] = None
