"""Lightweight telemetry emitter with opt-in JSONL backend.

The goal is to stay privacy-safe:
- Never log full commands, outputs, paths, URLs, or user text.
- Only emit small, structured metadata that can be sampled or exported later.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NoopTelemetry:
    """Telemetry stub when telemetry is disabled."""

    def emit(self, _event: dict[str, Any]) -> None:  # pragma: no cover - trivial
        return


@dataclass
class TelemetryConfig:
    """Simple configuration for the telemetry emitter."""

    enabled: bool
    path: Path
    service_name: str = "uatu"
    service_version: str | None = None


class TelemetryEmitter:
    """JSONL-based telemetry emitter."""

    def __init__(self, config: TelemetryConfig):
        self.config = config
        self.config.path = self.config.path.expanduser()

    def emit(self, event: dict[str, Any]) -> None:
        """Emit a telemetry event.

        Event is enriched with timestamp and basic resource attributes.
        Failures are swallowed to avoid impacting the user experience.
        """
        if not self.config.enabled:
            return

        try:
            self.config.path.parent.mkdir(parents=True, exist_ok=True)
            enriched = {
                "ts": event.get("ts", time.time()),
                "resource": {
                    "service.name": self.config.service_name,
                    "service.version": self.config.service_version,
                },
                **event,
            }
            line = json.dumps(enriched, separators=(",", ":"), ensure_ascii=False)
            with self.config.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Telemetry must never break the primary flow
            return


def summarize_command(command: str | None) -> dict[str, Any]:
    """Return a privacy-safe summary of a shell command.

    Captures only:
    - base command token
    - up to a few flags (strings starting with '-')
    - total length of the command string
    """
    if not command:
        return {}

    summary: dict[str, Any] = {"command_length": len(command)}
    try:
        tokens = shlex.split(command)
    except Exception:
        return summary

    if tokens:
        summary["base_cmd"] = tokens[0]
        flags = [tok for tok in tokens[1:] if tok.startswith("-")]
        if flags:
            summary["flags"] = flags[:5]
    return summary


def hash_with_salt(salt: str, text: str) -> str:
    """Return a salted SHA-256 hash of text (without storing the text).

    Args:
        salt: Per-session salt
        text: Text to hash

    Returns:
        Hex digest string
    """
    data = f"{salt}{text}".encode("utf-8", "ignore")
    return hashlib.sha256(data).hexdigest()

