"""Tests for investigation logging and quiet mode."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from uatu.watcher.async_handlers import InvestigationLogger
from uatu.watcher.models import AnomalyEvent, AnomalyType, Severity, SystemSnapshot


@pytest.fixture
def temp_log_file(tmp_path: Path) -> Path:
    """Create a temporary log file."""
    return tmp_path / "investigations.jsonl"


@pytest.fixture
def sample_event() -> AnomalyEvent:
    """Create a sample anomaly event."""
    return AnomalyEvent(
        timestamp=datetime.now(),
        type=AnomalyType.CPU_SPIKE,
        severity=Severity.WARNING,
        message="CPU spike detected",
        details={"cpu_percent": 95.0, "baseline": 50.0},
    )


@pytest.fixture
def sample_snapshot() -> SystemSnapshot:
    """Create a sample system snapshot."""
    return SystemSnapshot(
        timestamp=datetime.now(),
        cpu_percent=95.0,
        memory_percent=65.0,
        memory_used_mb=8192.0,
        memory_total_mb=16384.0,
        load_1min=2.5,
        load_5min=2.0,
        load_15min=1.5,
        process_count=150,
    )


class TestInvestigationLogger:
    """Test InvestigationLogger functionality."""

    @pytest.mark.asyncio
    async def test_logs_investigation_to_file(
        self,
        temp_log_file: Path,
        sample_event: AnomalyEvent,
        sample_snapshot: SystemSnapshot,
    ):
        """Test that investigations are written to log file."""
        logger = InvestigationLogger(temp_log_file)
        result = {"analysis": "This is a test investigation", "cached": False}

        await logger.log_investigation(sample_event, result, sample_snapshot)

        # Verify file was created and contains data
        assert temp_log_file.exists()
        with open(temp_log_file) as f:
            lines = f.readlines()
            assert len(lines) == 1

            # Parse JSON
            data = json.loads(lines[0])
            assert "timestamp" in data
            assert data["event"]["message"] == "CPU spike detected"
            assert data["event"]["severity"] == "warning"
            assert data["system"]["cpu_percent"] == 95.0
            assert data["investigation"]["analysis"] == "This is a test investigation"
            assert data["investigation"]["cached"] is False

    @pytest.mark.asyncio
    async def test_multiple_investigations(
        self,
        temp_log_file: Path,
        sample_event: AnomalyEvent,
        sample_snapshot: SystemSnapshot,
    ):
        """Test that multiple investigations are appended correctly."""
        logger = InvestigationLogger(temp_log_file)

        # Log three investigations
        for i in range(3):
            result = {"analysis": f"Investigation {i}", "cached": False}
            await logger.log_investigation(sample_event, result, sample_snapshot)

        # Verify all three are in file
        with open(temp_log_file) as f:
            lines = f.readlines()
            assert len(lines) == 3

            for i, line in enumerate(lines):
                data = json.loads(line)
                assert data["investigation"]["analysis"] == f"Investigation {i}"

    @pytest.mark.asyncio
    async def test_cached_investigation_metadata(
        self,
        temp_log_file: Path,
        sample_event: AnomalyEvent,
        sample_snapshot: SystemSnapshot,
    ):
        """Test that cache metadata is logged correctly."""
        logger = InvestigationLogger(temp_log_file)
        result = {
            "analysis": "Cached analysis",
            "cached": True,
            "cache_count": 5,
        }

        await logger.log_investigation(sample_event, result, sample_snapshot)

        with open(temp_log_file) as f:
            data = json.loads(f.read())
            assert data["investigation"]["cached"] is True
            assert data["investigation"]["cache_count"] == 5

    @pytest.mark.asyncio
    async def test_creates_parent_directory(
        self, tmp_path: Path, sample_event: AnomalyEvent, sample_snapshot: SystemSnapshot
    ):
        """Test that parent directories are created if they don't exist."""
        log_file = tmp_path / "nested" / "dir" / "investigations.jsonl"
        logger = InvestigationLogger(log_file)

        result = {"analysis": "Test", "cached": False}
        await logger.log_investigation(sample_event, result, sample_snapshot)

        assert log_file.exists()
        assert log_file.parent.exists()

    @pytest.mark.asyncio
    async def test_default_log_path(self):
        """Test that default log path is used if none provided."""
        logger = InvestigationLogger()
        expected_path = Path.home() / ".uatu" / "investigations.jsonl"
        assert logger.log_file == expected_path


class TestSeverityComparison:
    """Test Severity IntEnum comparison."""

    def test_severity_ordering(self):
        """Test that severity levels can be compared directly."""
        assert Severity.INFO < Severity.WARNING
        assert Severity.WARNING < Severity.ERROR
        assert Severity.ERROR < Severity.CRITICAL

        assert Severity.CRITICAL > Severity.ERROR
        assert Severity.ERROR > Severity.WARNING
        assert Severity.WARNING > Severity.INFO

    def test_severity_equality(self):
        """Test severity equality."""
        assert Severity.WARNING == Severity.WARNING
        assert Severity.ERROR == Severity.ERROR
        assert not (Severity.WARNING == Severity.ERROR)

    def test_severity_gte_lte(self):
        """Test >= and <= operators."""
        assert Severity.WARNING >= Severity.INFO
        assert Severity.WARNING >= Severity.WARNING
        assert not (Severity.WARNING >= Severity.ERROR)

        assert Severity.WARNING <= Severity.ERROR
        assert Severity.WARNING <= Severity.WARNING
        assert not (Severity.WARNING <= Severity.INFO)

    def test_severity_string_value(self):
        """Test string_value property for JSON serialization."""
        assert Severity.INFO.string_value == "info"
        assert Severity.WARNING.string_value == "warning"
        assert Severity.ERROR.string_value == "error"
        assert Severity.CRITICAL.string_value == "critical"

    def test_severity_from_string(self):
        """Test from_string classmethod for deserialization."""
        assert Severity.from_string("info") == Severity.INFO
        assert Severity.from_string("warning") == Severity.WARNING
        assert Severity.from_string("error") == Severity.ERROR
        assert Severity.from_string("critical") == Severity.CRITICAL

        # Test case insensitivity
        assert Severity.from_string("INFO") == Severity.INFO
        assert Severity.from_string("Warning") == Severity.WARNING

    def test_severity_from_string_invalid(self):
        """Test that invalid string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            Severity.from_string("invalid")

        with pytest.raises(ValueError, match="Invalid severity"):
            Severity.from_string("medium")
