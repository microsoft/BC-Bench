from types import MappingProxyType

import pytest

from bcbench_core.agent.env import agent_subprocess_env


def test_preserves_all_parent_vars_by_default():
    parent = {"PATH": "explicit", "PRIVATE_TOKEN": "preserved"}

    env = agent_subprocess_env(parent)

    assert env == parent
    assert env is not parent
    env["PATH"] = "changed"
    assert parent["PATH"] == "explicit"


def test_excludes_only_caller_selected_names_and_prefixes():
    parent = {
        "PATH": "explicit",
        "TOKEN": "withheld",
        "TOKEN_EXPIRY": "preserved",
        "AUTH_PASSWORD": "withheld",
        "AUTHENTICATED": "preserved",
        "PRIVATE_URL": "withheld",
    }

    env = agent_subprocess_env(parent, exclude_vars=frozenset({"TOKEN"}), exclude_prefixes=("AUTH_", "PRIVATE_"))

    assert env == {"PATH": "explicit", "TOKEN_EXPIRY": "preserved", "AUTHENTICATED": "preserved"}


def test_applies_explicit_overrides_after_exclusions_without_mutating_inputs():
    parent = MappingProxyType({"PATH": "original", "PRIVATE_TOKEN": "parent"})
    overrides = MappingProxyType({"PATH": "overridden", "PRIVATE_TOKEN": "explicit", "FLAG": "on"})

    env = agent_subprocess_env(parent, overrides, exclude_prefixes=("PRIVATE_",))

    assert env == {"PATH": "overridden", "PRIVATE_TOKEN": "explicit", "FLAG": "on"}
    assert parent == {"PATH": "original", "PRIVATE_TOKEN": "parent"}
    assert overrides == {"PATH": "overridden", "PRIVATE_TOKEN": "explicit", "FLAG": "on"}


def test_uses_only_the_supplied_parent_environment(monkeypatch):
    monkeypatch.setenv("UNRELATED_PROCESS_VAR", "not inherited")

    assert agent_subprocess_env({"PATH": "explicit"}) == {"PATH": "explicit"}


@pytest.mark.parametrize("overrides", [None, {}])
def test_empty_overrides_preserve_filtered_environment(overrides):
    assert agent_subprocess_env({"PATH": "explicit", "TOKEN": "withheld"}, overrides, exclude_vars=("TOKEN",)) == {"PATH": "explicit"}
