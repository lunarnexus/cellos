"""Attention and processing metadata for CelloS domain models."""

from datetime import datetime

from pydantic import BaseModel

from cellos.domain.time import utc_now
from cellos.domain.enums import AttentionReason


class AttentionMetadata(BaseModel):
    required: bool = False
    reason: AttentionReason | None = None
    detail: str = ""
    since: datetime | None = None

    @classmethod
    def required_attention(cls, reason: AttentionReason, detail: str = "") -> "AttentionMetadata":
        return cls(required=True, reason=reason, detail=detail, since=utc_now())

    def cleared(self) -> "AttentionMetadata":
        return AttentionMetadata()


class ProcessingMetadata(BaseModel):
    last_processed_at: datetime | None = None
    last_human_change_at: datetime | None = None
    last_ai_change_at: datetime | None = None
    last_observed_external_change_at: datetime | None = None
    last_processed_external_change_at: datetime | None = None
    last_processed_input_hash: str | None = None
