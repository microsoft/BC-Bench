"""Tests for version utility."""

from bcbench.results.summary import _get_benchmark_version


def test_get_benchmark_version_returns_string():
    version = _get_benchmark_version()
    assert isinstance(version, str)
    assert version != "unknown"


def test_get_benchmark_version_follows_semver_format():
    version = _get_benchmark_version()
    # Should match semver pattern like "0.1.0" or "1.0.0"
    parts = version.split(".")
    assert len(parts) >= 2, f"Version should have at least 2 parts: {version}"
    assert all(part.isdigit() for part in parts[:3]), f"Version parts should be numeric: {version}"
