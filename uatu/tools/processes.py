"""Process analysis tool for detecting issues like crash loops, zombies, and resource hogs."""

import subprocess
from dataclasses import dataclass
from typing import Any

import psutil


@dataclass
class ProcessInfo:
    """Information about a running process."""

    pid: int
    name: str
    user: str
    status: str
    cpu_percent: float
    memory_mb: float
    num_threads: int
    create_time: float
    cmdline: list[str]
    parent_pid: int | None


class ProcessAnalyzer:
    """Analyzes system processes to detect common issues."""

    @staticmethod
    def get_process_tree() -> str:
        """
        Get process tree similar to `ps -ef --forest`.

        Returns:
            Formatted process tree as string
        """
        try:
            # Try Linux format first
            result = subprocess.run(
                ["ps", "-ef", "--forest"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,  # Don't raise on non-zero exit
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Fallback for macOS (no --forest option)
        try:
            result = subprocess.run(
                ["ps", "-ef"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return result.stdout
        except subprocess.SubprocessError as e:
            return f"Error getting process tree: {e}"

    @staticmethod
    def get_process_info(pid: int) -> ProcessInfo | None:
        """
        Get detailed information about a specific process.

        Args:
            pid: Process ID

        Returns:
            ProcessInfo object or None if process doesn't exist
        """
        try:
            proc = psutil.Process(pid)
            return ProcessInfo(
                pid=proc.pid,
                name=proc.name(),
                user=proc.username(),
                status=proc.status(),
                cpu_percent=proc.cpu_percent(interval=0.1),
                memory_mb=proc.memory_info().rss / 1024 / 1024,
                num_threads=proc.num_threads(),
                create_time=proc.create_time(),
                cmdline=proc.cmdline(),
                parent_pid=proc.ppid(),
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    @staticmethod
    def find_high_cpu_processes(threshold: float = 10.0) -> list[ProcessInfo]:
        """
        Find processes using high CPU.

        Args:
            threshold: CPU percentage threshold (default: 10%)

        Returns:
            List of ProcessInfo for processes exceeding threshold
        """
        high_cpu: list[ProcessInfo] = []

        for proc in psutil.process_iter():
            try:
                cpu_percent = proc.cpu_percent(interval=0.1)
                if cpu_percent > threshold:
                    info = ProcessAnalyzer.get_process_info(proc.pid)
                    if info:
                        high_cpu.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return sorted(high_cpu, key=lambda x: x.cpu_percent, reverse=True)

    @staticmethod
    def find_high_memory_processes(threshold_mb: float = 500.0) -> list[ProcessInfo]:
        """
        Find processes using high memory.

        Args:
            threshold_mb: Memory threshold in MB (default: 500MB)

        Returns:
            List of ProcessInfo for processes exceeding threshold
        """
        high_mem: list[ProcessInfo] = []

        for proc in psutil.process_iter():
            try:
                memory_mb = proc.memory_info().rss / 1024 / 1024
                if memory_mb > threshold_mb:
                    info = ProcessAnalyzer.get_process_info(proc.pid)
                    if info:
                        high_mem.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return sorted(high_mem, key=lambda x: x.memory_mb, reverse=True)

    @staticmethod
    def find_zombie_processes() -> list[ProcessInfo]:
        """
        Find zombie processes (defunct).

        Returns:
            List of ProcessInfo for zombie processes
        """
        zombies: list[ProcessInfo] = []

        for proc in psutil.process_iter():
            try:
                if proc.status() == psutil.STATUS_ZOMBIE:
                    info = ProcessAnalyzer.get_process_info(proc.pid)
                    if info:
                        zombies.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return zombies

    @staticmethod
    def get_system_summary() -> dict[str, Any]:
        """
        Get overall system resource summary.

        Returns:
            Dictionary with CPU, memory, and process count information
        """
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        process_count = len(psutil.pids())

        return {
            "cpu_percent": cpu_percent,
            "memory_total_gb": memory.total / 1024 / 1024 / 1024,
            "memory_used_gb": memory.used / 1024 / 1024 / 1024,
            "memory_percent": memory.percent,
            "process_count": process_count,
        }
