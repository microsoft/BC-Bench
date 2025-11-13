"""
Integration test for custom instructions config loading.
"""

from pathlib import Path

import yaml


def test_config_has_instructions_section():
    """Verify that config.yaml has the instructions section."""
    config_path = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot" / "config.yaml"
    config = yaml.safe_load(config_path.read_text())

    assert "instructions" in config, "Config should have instructions section"
    assert isinstance(config["instructions"], dict), "Instructions should be a dict"
    assert "enabled" in config["instructions"], "Instructions should have enabled field"
    assert isinstance(config["instructions"]["enabled"], bool), "Enabled should be a boolean"
    print(f"✓ Config has instructions section: {config['instructions']}")


if __name__ == "__main__":
    print("Running config integration test...\n")
    test_config_has_instructions_section()
    print("\n✅ Config integration test passed!")
