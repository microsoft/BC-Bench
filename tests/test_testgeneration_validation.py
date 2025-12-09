from unittest.mock import patch

import pytest
import yaml

from bcbench.operations.setup_operations import _get_test_generation_input_mode


def test_get_test_generation_input_mode_valid_gold_patch():
    config_content = yaml.dump({"prompt": {"test-generation-input": "gold-patch"}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "gold-patch"


def test_get_test_generation_input_mode_valid_problem_statement():
    config_content = yaml.dump({"prompt": {"test-generation-input": "problem-statement"}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "problem-statement"


def test_get_test_generation_input_mode_defaults_to_problem_statement():
    config_content = yaml.dump({"prompt": {}})

    with patch("pathlib.Path.read_text", return_value=config_content):
        result = _get_test_generation_input_mode()

    assert result == "problem-statement"


def test_get_test_generation_input_mode_invalid_with_underscore():
    config_content = yaml.dump({"prompt": {"test-generation-input": "gold_patch"}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError) as exc_info:
        _get_test_generation_input_mode()

    assert "Invalid test-generation-input mode: 'gold_patch'" in str(exc_info.value)
    assert "gold-patch" in str(exc_info.value)
    assert "Use hyphens, not underscores" in str(exc_info.value)


def test_get_test_generation_input_mode_invalid_random_value():
    config_content = yaml.dump({"prompt": {"test-generation-input": "invalid-mode"}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError) as exc_info:
        _get_test_generation_input_mode()

    assert "Invalid test-generation-input mode: 'invalid-mode'" in str(exc_info.value)
    assert "gold-patch" in str(exc_info.value)
    assert "problem-statement" in str(exc_info.value)


def test_get_test_generation_input_mode_empty_string():
    config_content = yaml.dump({"prompt": {"test-generation-input": ""}})

    with patch("pathlib.Path.read_text", return_value=config_content), pytest.raises(ValueError) as exc_info:
        _get_test_generation_input_mode()

    assert "Invalid test-generation-input mode: ''" in str(exc_info.value)
