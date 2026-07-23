"""Tests for Home Assistant blueprints in ha-iguardstove."""

from pathlib import Path

import yaml

from custom_components.iguardstove.models import StoveEventType

BLUEPRINTS_DIR = (
    Path(__file__).parent.parent / "blueprints" / "automation" / "iguardstove"
)


class BlueprintCustomLoader(yaml.SafeLoader):
    """Custom YAML loader that ignores standard Home Assistant blueprint tags like !input."""


BlueprintCustomLoader.add_constructor(
    "!input", lambda loader, node: f"input_{node.value}"
)


def test_blueprints_exist_and_are_valid() -> None:
    """Test that blueprints directory exists and contains valid YAML blueprint files."""
    assert BLUEPRINTS_DIR.exists(), f"Blueprints directory not found: {BLUEPRINTS_DIR}"

    blueprint_files = list(BLUEPRINTS_DIR.glob("*.yaml"))
    assert len(blueprint_files) >= 2, "Expected at least 2 blueprint YAML files"

    for blueprint_file in blueprint_files:
        with open(blueprint_file, "r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=BlueprintCustomLoader)

        assert isinstance(data, dict), f"{blueprint_file.name} is not a valid dict"
        assert "blueprint" in data, f"{blueprint_file.name} missing 'blueprint' section"

        bp = data["blueprint"]
        assert bp.get("domain") == "automation", (
            f"{blueprint_file.name} domain must be 'automation'"
        )
        assert bp.get("name"), f"{blueprint_file.name} missing name"
        assert bp.get("description"), f"{blueprint_file.name} missing description"
        assert bp.get("homeassistant", {}).get("min_version"), (
            f"{blueprint_file.name} missing homeassistant.min_version"
        )
        assert "input" in bp, f"{blueprint_file.name} missing input section"

        # Verify event types input options match valid StoveEventType values
        if "event_types" in bp["input"]:
            select_opts = (
                bp["input"]["event_types"]
                .get("selector", {})
                .get("select", {})
                .get("options", [])
            )
            opt_values = [opt["value"] for opt in select_opts if isinstance(opt, dict)]
            known_types = {e.value for e in StoveEventType}
            for val in opt_values:
                assert val in known_types, (
                    f"Unknown event type {val} in {blueprint_file.name}"
                )

        # Safety policy verification: No blueprint should automatically unlock the stove
        raw_yaml_content = blueprint_file.read_text(encoding="utf-8")
        assert "lock.unlock" not in raw_yaml_content, (
            f"Safety violation: {blueprint_file.name} contains automatic unlock commands"
        )
