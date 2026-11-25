"""GET /api/stats (Requirement 9)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session as DBSession

from brain.api._common import get_db
from brain.schemas import StatsOut
from brain.stats import compute_stats

router = APIRouter()


@router.get("/api/stats", response_model=StatsOut)
def get_stats(db: Annotated[DBSession, Depends(get_db)]) -> StatsOut:
    return StatsOut(**compute_stats(db))
