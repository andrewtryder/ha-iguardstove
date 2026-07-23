"""Smoke test asserting all integration modules can be cleanly imported."""

import importlib
import py_compile
from pathlib import Path

CUSTOM_COMPONENTS_DIR = (
    Path(__file__).parent.parent / "custom_components" / "iguardstove"
)


def test_import_and_compile_all_modules() -> None:
    """Verify every python module in custom_components/iguardstove byte-compiles and imports."""
    py_files = sorted(CUSTOM_COMPONENTS_DIR.glob("**/*.py"))
    assert py_files, "No python files found in custom_components/iguardstove"

    for py_file in py_files:
        # Byte-compile check for syntax validity
        compiled_path = py_compile.compile(str(py_file), doraise=True)
        assert compiled_path is not None

        # Determine module dot path (e.g. custom_components.iguardstove.client)
        rel_path = py_file.relative_to(CUSTOM_COMPONENTS_DIR.parent.parent)
        module_name = ".".join(rel_path.with_suffix("").parts)

        imported = importlib.import_module(module_name)
        assert imported is not None
