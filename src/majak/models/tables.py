"""SQLAlchemy 2 ORM models mirroring the SQL migrations in supabase/migrations/.

These are used for reads/writes from the async API and pipeline. The migrations
remain the source of truth for DDL; these models must be kept in sync with them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from majak.config import settings


class Base(DeclarativeBase):
    pass


# Postgres enums — create_type=False because the migrations already define them.
source_kind_enum = ENUM(
    "transcript", "text", "email", "slack", "jira", "fathom", "calendar", "attachment", "image",
    name="source_kind", create_type=False,
)
day_status_enum = ENUM("draft", "open", "closed", name="day_status", create_type=False)
item_section_enum = ENUM(
    "top", "decision", "good", "threat", "deleg", "quick", "radar",
    name="item_section", create_type=False,
)
item_status_enum = ENUM("open", "done", "deleted", name="item_status", create_type=False)
list_kind_enum = ENUM("uloha", "napad", "poznamka", name="list_kind", create_type=False)
event_type_enum = ENUM(
    "create", "edit", "delete", "done", "reopen", "move", "tag", "carry",
    name="event_type", create_type=False,
)
review_kind_enum = ENUM(
    "person_ambiguous", "low_confidence_extract", "other",
    name="review_kind", create_type=False,
)


def _uuid_col() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    org: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    linkedin: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    first_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_seen: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aliases: Mapped[list[PersonAlias]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


class PersonAlias(Base):
    __tablename__ = "person_aliases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String, default="variant")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    person: Mapped[Person] = relationship(back_populates="aliases")


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(source_kind_enum)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connector: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceParticipant(Base):
    __tablename__ = "source_participants"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), primary_key=True)
    raw_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class Day(Base):
    __tablename__ = "days"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    status: Mapped[str] = mapped_column(day_status_enum, default="draft")
    pulse: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entered_day: Mapped[date | None] = mapped_column(ForeignKey("days.date"), nullable=True)
    section: Mapped[str] = mapped_column(item_section_enum)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rail: Mapped[str] = mapped_column(Text, default="signal")
    owners: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    chips: Mapped[list] = mapped_column(JSONB, default=list)
    list_kind: Mapped[str | None] = mapped_column(list_kind_enum, nullable=True)
    carry_from: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    status: Mapped[str] = mapped_column(item_status_enum, default="open")
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemSource(Base):
    __tablename__ = "item_sources"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), primary_key=True)
    # coalesce(locator,'') is the third PK column in SQL; we default to "" here.
    locator: Mapped[str] = mapped_column(Text, primary_key=True, default="")
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)


class ItemPerson(Base):
    __tablename__ = "item_people"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people.id"), primary_key=True)


class ItemEvent(Base):
    __tablename__ = "item_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(event_type_enum)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(Text, default="pavol")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    on_day: Mapped[date | None] = mapped_column(Date, nullable=True)


class ReviewQueue(Base):
    __tablename__ = "review_queue"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(review_kind_enum)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    connector: Mapped[str] = mapped_column(Text, primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class SourceChunk(Base):
    __tablename__ = "source_chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    chunk: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class ItemEmbedding(Base):
    __tablename__ = "item_embeddings"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class ExtractionHint(Base):
    __tablename__ = "extraction_hints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint: Mapped[str] = mapped_column(Text)
    created_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Kept importable for callers that only need a bool flag column elsewhere.
_ = (Boolean,)
