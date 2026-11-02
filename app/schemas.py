"""Pydantic models shared by the API, agents and tools."""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class Verdict(str, Enum):
    GO = "go"
    CAUTION = "caution"
    AVOID = "avoid"


class Evidence(BaseModel):
    """One reason behind a verdict, linked to the raw API response it came from."""

    source: str
    metric: str
    label: str
    verdict: Verdict
    message: str
    value: Optional[float] = None
    unit: str = ""
    threshold: Optional[float] = None
    url: str = ""
    ref: str = ""  # GET /evidence/{ref} returns the raw response


class DayVerdict(BaseModel):
    day: dt.date
    verdict: Verdict
    score: int = Field(ge=0, le=100)
    reasons: list[Evidence] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    agents: dict[str, Verdict] = Field(default_factory=dict)


class Tip(BaseModel):
    text: str
    url: str = ""


class Place(BaseModel):
    name: str
    lat: float
    lon: float
    distance_km: float


class Preferences(BaseModel):
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    motion_sickness: bool = False
    traveling_with_kids: bool = False
    elderly_travelers: bool = False


class PlanRequest(BaseModel):
    query: Optional[str] = Field(None, max_length=500, description="Free text, English/Bangla/Banglish")
    destination: Optional[str] = None
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None
    risk_tolerance: Optional[Literal["low", "medium", "high"]] = None
    language: Literal["en", "bn"] = "en"
    user_id: str = Field("default", max_length=64)
    confirm_caution: bool = False

    @model_validator(mode="after")
    def _need_something(self):
        if not (self.query or self.destination):
            raise ValueError("Provide either `query` or `destination`.")
        return self


PlanStatus = Literal["complete", "needs_approval", "rejected"]


class PlanResponse(BaseModel):
    plan_id: str
    status: PlanStatus
    destination: str
    destination_key: str
    start_date: dt.date
    end_date: dt.date
    days: list[DayVerdict]
    best_days: list[dt.date] = Field(default_factory=list)
    best_is_caution: bool = False
    avoid_days: list[dt.date] = Field(default_factory=list)
    narrative: str = ""
    narrative_source: str = "template"
    conflicts: list[str] = Field(default_factory=list)
    tips: list[Tip] = Field(default_factory=list)
    nearby_hospitals: list[Place] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    approval_question: Optional[str] = None
    tokens_used: int = 0


class DecisionRequest(BaseModel):
    approved: bool
    note: str = Field("", max_length=300)


class AskRequest(BaseModel):
    question: str = Field(..., max_length=500)
    user_id: str = "default"


class AskResponse(BaseModel):
    answer: str
    degraded: bool = False
    steps: list[dict] = Field(default_factory=list)
    tokens_used: int = 0
