"""Tests verifying strict socket isolation and loopback boundary enforcement."""

import socket

import pytest
import pytest_socket
from aresponses.main import ResponsesMockServer
from pytest_homeassistant_custom_component.plugins import HASocketBlockedError


def test_socket_creation_blocked_by_default() -> None:
    """Verify that creating internet sockets without a scoped loopback fixture is blocked."""
    with pytest.raises(pytest_socket.SocketBlockedError) as exc_info:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Narrowly remove only this test's deliberate exception instance so verify_cleanup
    # does not fail teardown, while preserving any unexpected socket attempt diagnostics.
    if (
        isinstance(exc_info.value, HASocketBlockedError)
        and exc_info.value in HASocketBlockedError.instances
    ):
        HASocketBlockedError.instances.remove(exc_info.value)


def test_dns_resolution_blocked_by_default() -> None:
    """Verify that external DNS resolution is blocked in standard tests."""
    with pytest.raises(RuntimeError, match="DNS resolution disabled in tests"):
        socket.getaddrinfo("example.com", 80)


async def test_external_ip_connection_blocked_under_aresponses(
    aresponses: ResponsesMockServer,
) -> None:
    """Verify that external IP connection is blocked even when aresponses is active."""
    # aresponses enables loopback socket creation for the local mock server,
    # but outbound connection to non-loopback IPs must be blocked.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(pytest_socket.SocketConnectBlockedError):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()


async def test_external_dns_resolution_blocked_under_aresponses(
    aresponses: ResponsesMockServer,
) -> None:
    """Verify that DNS resolution remains blocked when aresponses is active."""
    with pytest.raises(RuntimeError, match="DNS resolution disabled in tests"):
        socket.getaddrinfo("example.com", 80)
