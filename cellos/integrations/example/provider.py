"""Minimal example PM connector implementing the generic provider contract."""

from __future__ import annotations

from cellos.integrations.base import IntegrationProvider, IntegrationStatus, SetupResult, SyncDelta


class ExampleProvider(IntegrationProvider):
    """Tiny reference implementation for new PM connectors."""

    PROVIDER_NAME = "example"
    PROVIDER_DESCRIPTION = "Example PM connector"

    def __init__(self, **kwargs) -> None:
        self._kwargs = kwargs

    @property
    def provider_name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def provider_description(self) -> str:
        return self.PROVIDER_DESCRIPTION

    async def is_configured(self) -> bool:
        return False

    async def setup(self) -> SetupResult:
        return SetupResult(
            target_id="example-target",
            mappings={"backlog": "example-backlog"},
            details={"note": "Example provider is a template only"},
        )

    async def status(self) -> IntegrationStatus:
        return IntegrationStatus(
            provider_name=self.provider_name,
            configured=False,
            credentials_configured=False,
            board_or_target=None,
            details={"note": "Example provider is for authoring guidance and tests"},
        )

    async def sync(self, push: bool = True, pull: bool = True) -> SyncDelta:
        return SyncDelta()

    async def auto_push(self) -> SyncDelta:
        return SyncDelta()

    async def auto_pull_maybe(self, pull_interval_seconds: int) -> SyncDelta:
        return SyncDelta()
