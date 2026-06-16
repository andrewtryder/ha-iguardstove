"""Fixtures for iGuardStove integration testing."""

import threading

import pytest

# Monkeypatch threading.enumerate to prevent pycares safe shutdown loop threads
# from triggering false-positive thread leak assertions in pytest.
_original_enumerate = threading.enumerate


def _patched_enumerate():
    return [t for t in _original_enumerate() if "_run_safe_shutdown_loop" not in t.name]


threading.enumerate = _patched_enumerate

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in Home Assistant tests."""
    yield
