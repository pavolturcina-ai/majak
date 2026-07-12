"""Manual input: POST /inputs (text | file | image) → runs the real pipeline."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from majak.api.deps import CurrentUser, DbSession
from majak.ingest.pipeline import ingest
from majak.models.schemas import IngestResult, RawInput

router = APIRouter(prefix="/inputs", tags=["inputs"])

_IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


@router.post("", response_model=IngestResult, dependencies=[CurrentUser])
async def create_input(
    day: date | None = Form(default=None),
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    session: AsyncSession = DbSession,
) -> IngestResult:
    """Manual supplement — goes through the exact same 8-step pipeline."""
    raw = RawInput(kind="text", connector="manual", occurred_on=day, title=title)

    if text is not None:
        raw.kind = "text"
        raw.text = text
    elif image is not None:
        raw.kind = "image"
        raw.image_bytes = await image.read()
        raw.mime = image.content_type
        raw.file_name = image.filename
    elif file is not None:
        data = await file.read()
        raw.file_bytes = data
        raw.file_name = file.filename
        raw.mime = file.content_type
        raw.kind = "image" if (file.content_type or "") in _IMAGE_MIMES else "attachment"
        if raw.kind == "image":
            raw.image_bytes = data

    return await ingest(session, raw)
