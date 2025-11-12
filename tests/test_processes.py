"""Tests for process analysis tools."""


from uatu.tools import ProcessAnalyzer


def test_get_process_tree() -> None:
    """Test getting process tree."""
    analyzer = ProcessAnalyzer()
    tree = analyzer.get_process_tree()

    assert isinstance(tree, str)
    assert len(tree) > 0
    # Should contain some common process names
    assert "python" in tree.lower() or "bash" in tree.lower()


def test_get_system_summary() -> None:
    """Test getting system summary."""
    analyzer = ProcessAnalyzer()
    summary = analyzer.get_system_summary()

    assert "cpu_percent" in summary
    assert "memory_total_gb" in summary
    assert "memory_used_gb" in summary
    assert "memory_percent" in summary
    assert "process_count" in summary

    # Sanity checks
    assert 0 <= summary["cpu_percent"] <= 100
    assert 0 <= summary["memory_percent"] <= 100
    assert summary["memory_total_gb"] > 0
    assert summary["process_count"] > 0


def test_find_high_cpu_processes() -> None:
    """Test finding high CPU processes."""
    analyzer = ProcessAnalyzer()
    # Use a high threshold so test doesn't fail on idle systems
    processes = analyzer.find_high_cpu_processes(threshold=99.0)

    assert isinstance(processes, list)
    # All processes should exceed threshold if any found
    for proc in processes:
        assert proc.cpu_percent >= 99.0


def test_find_high_memory_processes() -> None:
    """Test finding high memory processes."""
    analyzer = ProcessAnalyzer()
    # Use very high threshold
    processes = analyzer.find_high_memory_processes(threshold_mb=10000.0)

    assert isinstance(processes, list)
    # All processes should exceed threshold if any found
    for proc in processes:
        assert proc.memory_mb >= 10000.0


def test_find_zombie_processes() -> None:
    """Test finding zombie processes."""
    analyzer = ProcessAnalyzer()
    zombies = analyzer.find_zombie_processes()

    assert isinstance(zombies, list)
    # We hope there are no zombies, but if there are, they should have the right status
    for proc in zombies:
        assert proc.status == "zombie"
