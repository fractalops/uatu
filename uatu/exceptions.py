"""Custom exceptions for Uatu.

This module defines the exception hierarchy for Uatu, providing more specific
error types than generic ValueError/RuntimeError.
"""


class UatuError(Exception):
    """Base exception for all Uatu-specific errors."""

    pass


# Permission and Security Exceptions


class PermissionError(UatuError):
    """Base exception for permission-related errors."""

    pass


class CommandDeniedError(PermissionError):
    """Raised when a command is denied by security policy."""

    pass


class SuspiciousPatternError(PermissionError):
    """Raised when a command contains suspicious patterns."""

    pass


class ReadOnlyModeError(PermissionError):
    """Raised when attempting bash commands in read-only mode."""

    pass


# Allowlist Exceptions


class AllowlistError(UatuError):
    """Base exception for allowlist-related errors."""

    pass


class InvalidCommandError(AllowlistError):
    """Raised when attempting to add an invalid command to the allowlist."""

    pass


class DuplicateCommandError(AllowlistError):
    """Raised when attempting to add a command that already exists."""

    pass


class CommandNotFoundError(AllowlistError):
    """Raised when attempting to remove a non-existent command."""

    pass


# Network Exceptions


class NetworkError(UatuError):
    """Base exception for network-related errors."""

    pass


class InvalidURLError(NetworkError):
    """Raised when a URL fails validation."""

    pass


class SSRFError(NetworkError):
    """Raised when SSRF attempt is detected."""

    pass


class DomainNotAllowedError(NetworkError):
    """Raised when accessing a domain not in the allowlist."""

    pass


class NetworkCommandBlockedError(PermissionError):
    """Raised when a network command is blocked (curl, wget, etc.)."""

    pass


# Configuration Exceptions


class ConfigError(UatuError):
    """Base exception for configuration errors."""

    pass


class MissingAPIKeyError(ConfigError):
    """Raised when required API key is not set."""

    pass


class InvalidSettingError(ConfigError):
    """Raised when a configuration setting has an invalid value."""

    pass


# Audit Exceptions


class AuditError(UatuError):
    """Base exception for audit-related errors."""

    pass


class AuditLogWriteError(AuditError):
    """Raised when audit log cannot be written."""

    pass
