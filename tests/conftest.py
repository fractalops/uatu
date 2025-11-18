"""Pytest fixtures for Uatu tests."""

import pytest


@pytest.fixture
def temp_log_file(tmp_path):
    """Create a temporary log file for testing."""
    return tmp_path / "test_events.jsonl"
