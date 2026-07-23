"""Smoke test asserting all integration modules can be cleanly imported."""

import importlib

MODULES = [
    "custom_components.iguardstove",
    "custom_components.iguardstove.client",
    "custom_components.iguardstove.config_flow",
    "custom_components.iguardstove.const",
    "custom_components.iguardstove.coordinator",
    "custom_components.iguardstove.diagnostics",
    "custom_components.iguardstove.entity",
    "custom_components.iguardstove.event",
    "custom_components.iguardstove.exceptions",
    "custom_components.iguardstove.lock",
    "custom_components.iguardstove.models",
    "custom_components.iguardstove.parser",
    "custom_components.iguardstove.sensor",
    "custom_components.iguardstove.types",
]


def test_import_all_modules() -> None:
    """Verify every integration module imports without syntax or import errors."""
    for module_name in MODULES:
        imported = importlib.import_module(module_name)
        assert imported is not None
