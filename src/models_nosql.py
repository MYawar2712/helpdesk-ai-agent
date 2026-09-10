"""Pydantic schemas for unstructured support communications."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TranscriptMessage(BaseModel):
    """One message in a support transcript."""

    model_config = ConfigDict(strict=True, extra="forbid")

    sender: str = Field(min_length=1)
    text: str
    timestamp: datetime


class TranscriptMetadata(BaseModel):
    """Context captured alongside a transcript."""

    model_config = ConfigDict(strict=True, extra="forbid")

    device: str
    channel: str
    duration: int = Field(ge=0)


class ChatTranscript(BaseModel):
    """Validated unstructured chat transcript document."""

    model_config = ConfigDict(strict=True, extra="forbid")

    transcript_id: str = Field(min_length=1)
    ticket_id: str | None = None
    customer_id: str = Field(min_length=1)
    messages: list[TranscriptMessage] = Field(min_length=1)
    metadata: TranscriptMetadata
    created_at: datetime
