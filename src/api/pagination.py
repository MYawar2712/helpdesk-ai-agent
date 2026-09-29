"""Reusable pagination model and pagination calculation helper."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination response wrapper."""

    items: list[T]
    page: int = Field(ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(ge=1, le=100, description="Items per page")
    total: int = Field(ge=0, description="Total matching items count")
    pages: int = Field(ge=0, description="Total number of pages")


def build_paginated_response(
    items: list[T],
    total: int,
    page: int,
    page_size: int,
) -> PaginatedResponse[T]:
    """Calculate page count and return standard PaginatedResponse."""
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return PaginatedResponse[T](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
    )
