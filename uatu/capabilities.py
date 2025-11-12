"""Tool capability detection for adaptive tool selection."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolCapabilities:
    """Detected system capabilities for adaptive tool selection."""

    # Tier 0: Kernel filesystems (always check these first)
    has_proc: bool = False
    has_sys: bool = False

    # Tier 1: Core POSIX utilities
    has_ps: bool = False
    has_lsof: bool = False

    # Tier 2: Common admin tools
    has_ss: bool = False
    has_netstat: bool = False
    has_systemctl: bool = False
    has_journalctl: bool = False

    # Tier 3: Enhanced tools
    has_strace: bool = False

    # Special capabilities
    is_root: bool = False
    in_container: bool = False

    @classmethod
    def detect(cls) -> "ToolCapabilities":
        """Detect available tools and capabilities."""
        caps = cls()

        # Tier 0: Kernel filesystems
        caps.has_proc = Path("/proc").exists()
        caps.has_sys = Path("/sys").exists()

        # Tier 1: Core utilities
        caps.has_ps = cls._command_exists("ps")
        caps.has_lsof = cls._command_exists("lsof")

        # Tier 2: Admin tools
        caps.has_ss = cls._command_exists("ss")
        caps.has_netstat = cls._command_exists("netstat")
        caps.has_systemctl = cls._command_exists("systemctl")
        caps.has_journalctl = cls._command_exists("journalctl")

        # Tier 3: Enhanced
        caps.has_strace = cls._command_exists("strace")

        # Special
        caps.is_root = os.geteuid() == 0
        caps.in_container = cls._in_container()

        return caps

    @staticmethod
    def _command_exists(command: str) -> bool:
        """Check if a command is available in PATH."""
        return shutil.which(command) is not None

    @staticmethod
    def _in_container() -> bool:
        """Detect if running inside a container."""
        # Docker
        if Path("/.dockerenv").exists():
            return True

        # Podman
        if Path("/run/.containerenv").exists():
            return True

        # Check cgroup
        try:
            cgroup = Path("/proc/self/cgroup").read_text()
            if any(x in cgroup for x in ["docker", "kubepods", "lxc"]):
                return True
        except (FileNotFoundError, PermissionError):
            pass

        return False
