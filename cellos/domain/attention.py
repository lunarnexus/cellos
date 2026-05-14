"""Compatibility shim for `cellos.models` attention types."""

from cellos.models import AttentionMetadata, AttentionReason, ProcessingMetadata

__all__ = ["AttentionMetadata", "AttentionReason", "ProcessingMetadata"]
