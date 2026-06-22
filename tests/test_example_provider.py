from __future__ import annotations

import pytest


class TestExampleProvider:
    def test_registry_discovers_example_provider(self):
        from cellos.integrations.registry import get_providers

        providers = get_providers()
        assert "example" in providers

    def test_load_example_provider(self):
        from cellos.integrations.registry import load_provider

        prov = load_provider("example")
        assert prov.provider_name == "example"
        assert prov.provider_description == "Example PM connector"

    @pytest.mark.asyncio
    async def test_example_provider_contract_shape(self):
        from cellos.integrations.base import IntegrationStatus, SetupResult, SyncDelta
        from cellos.integrations.registry import load_provider

        prov = load_provider("example")

        assert await prov.is_configured() is False

        setup = await prov.setup()
        assert isinstance(setup, SetupResult)
        assert setup.target_id == "example-target"
        assert setup.mappings == {"backlog": "example-backlog"}

        status = await prov.status()
        assert isinstance(status, IntegrationStatus)
        assert status.provider_name == "example"

        delta = await prov.sync()
        assert isinstance(delta, SyncDelta)
