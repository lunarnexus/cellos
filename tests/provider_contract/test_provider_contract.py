from __future__ import annotations

import pytest


@pytest.mark.parametrize("provider_name", ["example", "vikunja"])
def test_provider_registry_loads_known_provider(provider_name):
    from cellos.integrations.registry import load_provider

    prov = load_provider(provider_name)
    assert prov.provider_name == provider_name
    assert prov.provider_description


@pytest.mark.asyncio
async def test_example_provider_returns_generic_status_and_setup_shapes():
    from cellos.integrations.base import IntegrationStatus, SetupResult, SyncDelta
    from cellos.integrations.registry import load_provider

    prov = load_provider("example")

    setup = await prov.setup()
    status = await prov.status()
    delta = await prov.sync()

    assert isinstance(setup, SetupResult)
    assert isinstance(status, IntegrationStatus)
    assert isinstance(delta, SyncDelta)


@pytest.mark.asyncio
async def test_example_provider_auto_hooks_return_syncdelta():
    from cellos.integrations.base import SyncDelta
    from cellos.integrations.registry import load_provider

    prov = load_provider("example")

    push_delta = await prov.auto_push()
    pull_delta = await prov.auto_pull_maybe(300)

    assert isinstance(push_delta, SyncDelta)
    assert isinstance(pull_delta, SyncDelta)
