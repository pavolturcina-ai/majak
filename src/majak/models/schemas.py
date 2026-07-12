"""Pydantic v2 schemas: pipeline domain objects + API request/response models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal[
    "transcript", "text", "email", "slack", "jira", "fathom", "calendar", "attachment", "image"
]
ItemSection = Literal["top", "decision", "good", "threat", "deleg", "quick", "radar"]
ItemStatus = Literal["open", "done", "deleted"]
ListKind = Literal["uloha", "napad", "poznamka"]
DayStatus = Literal["draft", "open", "closed"]
ReviewKind = Literal["person_ambiguous", "low_confidence_extract", "other"]


# ── Pipeline domain objects ──────────────────────────────────────────────────
class RawInput(BaseModel):
    """A single unit of input entering the pipeline from any origin."""

    kind: SourceKind
    connector: str = "manual"
    external_id: str | None = None
    title: str | None = None
    occurred_at: datetime | None = None
    occurred_on: date | None = None
    url: str | None = None
    # One of these carries the payload:
    text: str | None = None
    html: str | None = None
    file_bytes: bytes | None = None
    file_name: str | None = None
    mime: str | None = None
    image_bytes: bytes | None = None
    # Connector-specific extras (e.g. calendar attendee emails).
    meta: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


class Classification(BaseModel):
    kind: SourceKind
    occurred_on: date | None = None
    title: str
    topic_tags: list[str] = Field(default_factory=list)


class PersonRef(BaseModel):
    """A resolved (or to-be-resolved) person mention within a source."""

    raw_name: str
    person_id: uuid.UUID | None = None
    confidence: float = 0.0
    status: Literal["linked", "ambiguous", "new"] = "new"
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class Grounding(BaseModel):
    quote: str
    locator: str | None = None
    url: str | None = None


class ExtractedUnit(BaseModel):
    """One evaluation unit extracted from a source, before persistence."""

    section: ItemSection
    title: str
    description: str | None = None
    rail: str = "signal"
    owners: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)  # raw names, resolved downstream
    chips: list[dict[str, Any]] = Field(default_factory=list)
    grounding: list[Grounding] = Field(default_factory=list)
    confidence: float = 1.0


class IngestResult(BaseModel):
    source_id: uuid.UUID | None = None
    day: date | None = None
    created_item_ids: list[uuid.UUID] = Field(default_factory=list)
    carried_item_ids: list[uuid.UUID] = Field(default_factory=list)
    resolved_people: list[PersonRef] = Field(default_factory=list)
    review_ids: list[uuid.UUID] = Field(default_factory=list)
    skipped_duplicate: bool = False
    notes: list[str] = Field(default_factory=list)


# ── API response models ──────────────────────────────────────────────────────
class GroundingOut(BaseModel):
    source_id: uuid.UUID
    quote: str | None = None
    locator: str | None = None
    url: str | None = None


class ItemOut(BaseModel):
    id: uuid.UUID
    entered_day: date | None
    section: ItemSection
    title: str
    description: str | None
    rail: str
    owners: list[str]
    chips: list[dict[str, Any]]
    list_kind: ListKind | None
    carry_from: uuid.UUID | None
    status: ItemStatus
    status_at: datetime | None
    status_day: date | None
    order_index: int
    people: list[uuid.UUID] = Field(default_factory=list)
    grounding: list[GroundingOut] = Field(default_factory=list)


class DayView(BaseModel):
    date: date
    status: DayStatus
    pulse: str | None
    summary: str | None
    opened_at: datetime | None
    closed_at: datetime | None
    sections: dict[str, list[ItemOut]] = Field(default_factory=dict)


class PersonOut(BaseModel):
    id: uuid.UUID
    canonical_name: str
    role: str | None
    org: str | None
    email: str | None
    linkedin: str | None
    tags: list[str]
    first_seen: date | None
    last_seen: date | None


class PersonBrief(BaseModel):
    person: PersonOut
    sources: list[dict[str, Any]] = Field(default_factory=list)
    open_items: list[ItemOut] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    last_interactions: list[dict[str, Any]] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


# ── API request models ───────────────────────────────────────────────────────
class ItemPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    section: ItemSection | None = None
    rail: str | None = None
    owners: list[str] | None = None
    chips: list[dict[str, Any]] | None = None
    order_index: int | None = None


class StatusChange(BaseModel):
    status: ItemStatus
    reason: str | None = None


class ListTag(BaseModel):
    kind: ListKind | None = None


class ReorderRequest(BaseModel):
    ordered_ids: list[uuid.UUID]


class ResolvePersonRequest(BaseModel):
    raw_name: str
    context: str | None = None


class AliasRequest(BaseModel):
    alias: str
    kind: Literal["confirmed_typo", "variant", "nickname"] = "variant"


class ReviewResolveRequest(BaseModel):
    # For person_ambiguous: chosen person_id, or null to create-new.
    person_id: uuid.UUID | None = None
    create_new: bool = False
    dismiss: bool = False
    note: str | None = None
