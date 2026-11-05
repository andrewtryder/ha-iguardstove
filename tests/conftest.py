"""Fixtures for iGuardStove integration testing."""

import asyncio
import threading
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from aresponses.main import ResponsesMockServer

# Monkeypatch threading.enumerate to prevent pycares safe shutdown loop threads
# from triggering false-positive thread leak assertions in pytest.
_original_enumerate = threading.enumerate


def _patched_enumerate() -> list[threading.Thread]:
    return [t for t in _original_enumerate() if "_run_safe_shutdown_loop" not in t.name]


threading.enumerate = _patched_enumerate

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> Generator[None]:
    """Enable custom integrations in Home Assistant tests."""
    yield


@pytest.fixture
async def aresponses(
    socket_enabled: Any,
) -> AsyncGenerator[ResponsesMockServer]:
    """Narrowly permit loopback socket creation for in-process aresponses mock server."""
    loop = asyncio.get_running_loop()
    async with ResponsesMockServer(loop=loop) as server:
        yield server
