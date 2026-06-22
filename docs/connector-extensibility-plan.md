# Connector Extensibility Plan

**Goal:** Make it straightforward to add new PM connectors such as WeKan, Plane, and OpenProject without leaking provider-specific assumptions into core.

## Current baseline

- `cellos.integrations.base` is the generic provider contract
- `cellos.integrations.registry` handles discovery/loading
- provider-specific code belongs under `cellos/integrations/<provider>/`
- the example provider remains as the skeleton/reference implementation

## What good looks like

A new provider author should be able to:
1. create `cellos/integrations/<provider>/`
2. implement `provider.py` against `IntegrationProvider`
3. add client/models/mapper helpers only if needed
4. run provider-contract and CLI tests without touching core

## Guardrails

- no provider-specific workflow names in core
- no provider-specific field names treated as canonical in core
- no provider-specific setup rules in CLI or scheduler
- provider config stays under generic `integrations.providers`

## Short-term priority

Use this plan to support:
1. WeKan first
2. Plane second
3. OpenProject third

## Validation

- provider registry loads the new provider
- `pmcon list` shows it
- `pmcon status <provider>` works
- provider-specific tests cover setup/sync behavior
