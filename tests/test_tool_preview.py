"""Tests for tool result preview formatter."""

from uatu.ui.tool_preview import ToolPreviewFormatter


class TestBashPreview:
    """Test Bash command output previews."""

    def test_single_line_output(self):
        """Test single line bash output."""
        response = {"stdout": "Hello World"}
        preview = ToolPreviewFormatter.format_preview("Bash", response)
        assert preview == "✓ Hello World"

    def test_multiline_output(self):
        """Test multiline bash output shows all lines (up to 5)."""
        response = {"stdout": "USER     PID %CPU %MEM\nroot       1  0.0  0.1\nroot       2  0.0  0.0"}
        preview = ToolPreviewFormatter.format_preview("Bash", response)
        # Now shows multiple lines instead of just first line
        assert preview.startswith("✓ 3 lines")
        assert "USER     PID %CPU %MEM" in preview

    def test_empty_output(self):
        """Test empty bash output."""
        response = {"stdout": ""}
        preview = ToolPreviewFormatter.format_preview("Bash", response)
        assert preview == "✓ No output"

    def test_long_line_truncation(self):
        """Test long lines are truncated."""
        long_line = "x" * 200
        response = {"stdout": long_line}
        preview = ToolPreviewFormatter.format_preview("Bash", response)
        assert len(preview) <= 102  # MAX_PREVIEW_LENGTH + some chars for prefix
        assert preview.endswith("...")


class TestMCPPreview:
    """Test MCP tool previews."""

    def test_list_response(self):
        """Test list responses show count."""
        response = [{"id": 1}, {"id": 2}, {"id": 3}]
        preview = ToolPreviewFormatter.format_preview("mcp__system-tools__list_processes", response)
        assert "3" in preview
        assert "process" in preview.lower()

    def test_dict_response(self):
        """Test dict responses show field count."""
        response = {"cpu": "80%", "memory": "16GB", "uptime": "5 days"}
        preview = ToolPreviewFormatter.format_preview("mcp__system-tools__get_system_info", response)
        assert "3 fields" in preview

    def test_string_response(self):
        """Test short string responses."""
        response = "System is healthy"
        preview = ToolPreviewFormatter.format_preview("mcp__health__check", response)
        assert preview == "✓ System is healthy"


class TestNetworkPreview:
    """Test network tool previews."""

    def test_webfetch_preview(self):
        """Test WebFetch shows status and size."""
        response = {"status_code": 200, "content": "x" * 1000}
        preview = ToolPreviewFormatter.format_preview("WebFetch", response)
        assert "200" in preview
        assert "KB" in preview or "B" in preview

    def test_websearch_preview(self):
        """Test WebSearch shows result count."""
        response = [{"title": "Result 1"}, {"title": "Result 2"}]
        preview = ToolPreviewFormatter.format_preview("WebSearch", response)
        assert "2 results" in preview


class TestDefaultPreview:
    """Test default/generic previews."""

    def test_list(self):
        """Test generic list."""
        response = [1, 2, 3, 4, 5]
        preview = ToolPreviewFormatter.format_preview("custom_tool", response)
        assert "5 items" in preview

    def test_none(self):
        """Test None response."""
        preview = ToolPreviewFormatter.format_preview("custom_tool", None)
        assert "No result" in preview

    def test_number(self):
        """Test numeric response."""
        preview = ToolPreviewFormatter.format_preview("custom_tool", 42)
        assert "42" in preview


class TestBytesFormatting:
    """Test byte size formatting."""

    def test_bytes(self):
        """Test bytes formatting."""
        assert ToolPreviewFormatter._format_bytes(500) == "500B"

    def test_kilobytes(self):
        """Test kilobytes formatting."""
        assert ToolPreviewFormatter._format_bytes(2048) == "2.0KB"

    def test_megabytes(self):
        """Test megabytes formatting."""
        assert ToolPreviewFormatter._format_bytes(2 * 1024 * 1024) == "2.0MB"
