"""Pydantic models for Vikunja API payloads used by the provider."""

from __future__ import annotations

from pydantic import BaseModel


class VikunjaProject(BaseModel):
    id: int | str
    title: str | None = None
    name: str | None = None


class VikunjaBucket(BaseModel):
    id: int | str
    title: str | None = None
    name: str | None = None
