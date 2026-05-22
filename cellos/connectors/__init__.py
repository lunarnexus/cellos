"""Connector backends for agent execution."""

from cellos.connectors.base import TaskConnector
from cellos.connectors.fake_acp import FakeAcpConnector
from cellos.connectors.opencode import OpenCodeConnector

__all__ = [
    "TaskConnector",
    "FakeAcpConnector",
    "OpenCodeConnector",
]
