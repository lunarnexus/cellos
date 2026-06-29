"""Mapping helpers for Vikunja provider."""

from __future__ import annotations

from typing import Any


def normalize_bucket_title(bucket: dict[str, Any]) -> str:
    return str(bucket.get("title") or bucket.get("name") or "").strip().lower()
