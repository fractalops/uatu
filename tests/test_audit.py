"""Tests for security audit logging."""

import json

from uatu.audit import SecurityAuditor


class TestSecurityAuditor:
    """Tests for SecurityAuditor class."""

    def test_init_creates_log_dir(self, tmp_path):
        """Test that initialization creates log directory."""
        log_dir = tmp_path / "test_uatu"
        auditor = SecurityAuditor(log_dir=log_dir)

        assert log_dir.exists()
        assert auditor.audit_file == log_dir / "security.jsonl"

    def test_log_bash_approval(self, tmp_path):
        """Test logging bash command approval."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_bash_approval(
            command="ls -la",
            approved=True,
            added_to_allowlist=False,
            description="List files",
        )

        # Read and verify event
        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "bash_command_approval"
        assert event["command"] == "ls -la"
        assert event["description"] == "List files"
        assert event["approved"] is True
        assert event["added_to_allowlist"] is False
        assert "timestamp" in event

    def test_log_bash_denial(self, tmp_path):
        """Test logging bash command denial."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_bash_denial(
            command="rm -rf /",
            reason="User declined",
            description="Delete everything",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "bash_command_denied"
        assert event["command"] == "rm -rf /"
        assert event["reason"] == "User declined"
        assert event["description"] == "Delete everything"

    def test_log_bash_auto_approved(self, tmp_path):
        """Test logging auto-approved bash command."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_bash_auto_approved(
            command="git status",
            description="Check git status",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "bash_command_auto_approved"
        assert event["command"] == "git status"
        assert event["description"] == "Check git status"

    def test_log_network_approval(self, tmp_path):
        """Test logging network access approval."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_network_approval(
            tool_name="WebFetch",
            url="https://example.com",
            domain="example.com",
            approved=True,
            added_to_allowlist=True,
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "network_access_approval"
        assert event["tool"] == "WebFetch"
        assert event["url"] == "https://example.com"
        assert event["domain"] == "example.com"
        assert event["approved"] is True
        assert event["added_to_allowlist"] is True

    def test_log_network_auto_approved(self, tmp_path):
        """Test logging auto-approved network access."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_network_auto_approved(
            tool_name="WebFetch",
            url="https://docs.python.org",
            domain="docs.python.org",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "network_access_auto_approved"
        assert event["tool"] == "WebFetch"
        assert event["url"] == "https://docs.python.org"
        assert event["domain"] == "docs.python.org"

    def test_log_ssrf_blocked(self, tmp_path):
        """Test logging SSRF block."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_ssrf_blocked(
            tool_name="WebFetch",
            url="http://169.254.169.254",
            reason="Cloud metadata endpoint blocked",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "ssrf_blocked"
        assert event["tool"] == "WebFetch"
        assert event["url"] == "http://169.254.169.254"
        assert event["reason"] == "Cloud metadata endpoint blocked"
        assert event["severity"] == "high"

    def test_log_network_command_blocked(self, tmp_path):
        """Test logging blocked network command."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_network_command_blocked(
            command="curl http://example.com",
            base_command="curl",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "network_command_blocked"
        assert event["command"] == "curl http://example.com"
        assert event["base_command"] == "curl"
        assert event["severity"] == "medium"

    def test_log_suspicious_pattern(self, tmp_path):
        """Test logging suspicious pattern detection."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_suspicious_pattern(
            command="echo foo && rm -rf /",
            pattern=r"&&.*rm\s+-rf",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "suspicious_pattern_detected"
        assert event["command"] == "echo foo && rm -rf /"
        assert event["pattern"] == r"&&.*rm\s+-rf"
        assert event["severity"] == "medium"

    def test_log_allowlist_modification(self, tmp_path):
        """Test logging allowlist modification."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_allowlist_modification(
            action="added",
            entry_type="base",
            pattern="git",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "allowlist_modified"
        assert event["action"] == "added"
        assert event["entry_type"] == "base"
        assert event["pattern"] == "git"

    def test_log_network_allowlist_modification(self, tmp_path):
        """Test logging network allowlist modification."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        auditor.log_network_allowlist_modification(
            action="added",
            domain="example.com",
        )

        with open(auditor.audit_file) as f:
            event = json.loads(f.readline())

        assert event["event_type"] == "network_allowlist_modified"
        assert event["action"] == "added"
        assert event["domain"] == "example.com"

    def test_get_recent_events(self, tmp_path):
        """Test retrieving recent events."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        # Log several events
        auditor.log_bash_approval("cmd1", True, False)
        auditor.log_bash_approval("cmd2", True, False)
        auditor.log_bash_approval("cmd3", False, False)

        # Get recent events
        events = auditor.get_recent_events(limit=2)

        assert len(events) == 2
        # Most recent first
        assert events[0]["command"] == "cmd3"
        assert events[1]["command"] == "cmd2"

    def test_get_recent_events_empty(self, tmp_path):
        """Test getting events when file doesn't exist."""
        auditor = SecurityAuditor(log_dir=tmp_path)
        events = auditor.get_recent_events()

        assert events == []

    def test_get_events_by_type(self, tmp_path):
        """Test filtering events by type."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        # Log different event types
        auditor.log_bash_approval("cmd1", True, False)
        auditor.log_network_approval("WebFetch", "https://example.com", "example.com", True, False)
        auditor.log_bash_denial("cmd2", "reason")
        auditor.log_ssrf_blocked("WebFetch", "http://localhost", "localhost blocked")

        # Get only bash approvals
        bash_events = auditor.get_events_by_type("bash_command_approval")
        assert len(bash_events) == 1
        assert bash_events[0]["command"] == "cmd1"

        # Get only SSRF blocks
        ssrf_events = auditor.get_events_by_type("ssrf_blocked")
        assert len(ssrf_events) == 1
        assert ssrf_events[0]["url"] == "http://localhost"

    def test_get_security_summary(self, tmp_path):
        """Test security summary statistics."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        # Log various events
        auditor.log_bash_approval("cmd1", True, False)
        auditor.log_bash_approval("cmd2", False, False)
        auditor.log_bash_denial("cmd3", "reason")
        auditor.log_network_approval("WebFetch", "https://example.com", "example.com", True, False)
        auditor.log_network_approval("WebFetch", "https://evil.com", "evil.com", False, False)
        auditor.log_ssrf_blocked("WebFetch", "http://localhost", "localhost")
        auditor.log_network_command_blocked("curl http://example.com", "curl")
        auditor.log_suspicious_pattern("rm -rf /", r"rm\s+-rf")

        summary = auditor.get_security_summary()

        assert summary["total_events"] == 8
        assert summary["bash_approvals"] == 1
        assert summary["bash_denials"] == 2  # 1 denied approval + 1 denial
        assert summary["network_approvals"] == 1
        assert summary["network_denials"] == 1
        assert summary["ssrf_blocks"] == 1
        assert summary["network_command_blocks"] == 1
        assert summary["suspicious_patterns"] == 1

    def test_multiple_events_persistence(self, tmp_path):
        """Test that multiple events persist correctly in JSONL format."""
        auditor = SecurityAuditor(log_dir=tmp_path)

        # Log multiple events
        for i in range(5):
            auditor.log_bash_approval(f"cmd{i}", True, False)

        # Read file and verify JSONL format
        with open(auditor.audit_file) as f:
            lines = f.readlines()

        assert len(lines) == 5
        for i, line in enumerate(lines):
            event = json.loads(line)
            assert event["command"] == f"cmd{i}"

    def test_audit_file_permissions(self, tmp_path):
        """Test that audit file has restrictive permissions."""
        auditor = SecurityAuditor(log_dir=tmp_path)
        auditor.log_bash_approval("test", True, False)

        # Check file permissions (owner read/write only)
        stat = auditor.audit_file.stat()
        # On Unix, mode 0o600 = owner read/write only
        assert stat.st_mode & 0o777 == 0o600
