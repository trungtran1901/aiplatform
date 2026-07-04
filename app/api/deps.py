"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Query

from app.db.session import get_db  # noqa: F401  (re-exported for convenience)


class PaginationParams:
    def __init__(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
