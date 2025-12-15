# Uatu Internals

This document explains the architecture and implementation details of Uatu.

## Architecture Overview

### Two Operating Modes

**1) Interactive Chat Mode** (`uatu`)
- Long-lived conversation with maintained context
- Users ask, agent probes (MCP-first), users follow up
- Stateful client with persistent history
- Full tool surface: MCP + Bash (approval)

**2) Stdin Mode** (`echo "data" | uatu`)
- Single query from stdin, stateless
- Good for scripting/log analysis
- Same permissions/guardrails

### Core Components

#### Chat Session Layer (`uatu/chat_session/`)

- `session.py`: interactive + stdin modes; shows mode/budget/turn warnings; structured response scaffold (Conclusion → Evidence → Next steps).
- `handlers.py`: streams SDK messages; shows tool usage, previews, and per-tool timing; tracks stats.
- `commands.py`: slash commands (`/help`, `/exit`, `/clear`/`/reset`, `/allowlist`, `/recover` notice).

#### Tool Layer (`uatu/tools/`)

Via MCP servers:
- System tools: get_system_info, list_processes, get_process_tree, find_process_by_name, check_port_binding, read_proc_file.
- Safe-hints: top_processes, disk_usage_summary, listening_ports_hint.

Bash (SDK tool):
- Approval-gated; used sparingly when MCP/safe-hints are insufficient.

#### Permission System (`uatu/permissions.py`, `uatu/allowlist.py`)

- PreToolUse hook for all tools; Bash/network gated by approval/allowlist.
- Risk detection: credential, destructive, system-mod, suspicious patterns.
- Network allowlist + SSRF validation.
- Platform-aware guardrails (e.g., strace/ss denied on macOS).
- Allowlist (base/exact) stored under `~/.config/uatu/allowlist.json`.
- Audit logging for approvals/denials and network decisions.

#### UI Layer (`uatu/ui/`)

- `approval.py`: approval UI with risk levels and navigation.
- `console.py`: welcome/help, status/timing lines, tool usage previews, friendly tool names, backgrounding hints.
- `tool_preview.py`: concise previews with line counts/summaries.
- `markdown.py`: left-aligned, minimal markdown rendering.

#### CLI Layer (`uatu/cli.py`)

- Detects stdin vs interactive.
- Builds initial prompt.
- Delegates to ChatSession.run()/run_oneshot().
- Audit subcommand available.

## Key Technical Decisions

### MCP (Model Context Protocol)

Standardizes tool exposure:
- Portable tool definitions (system-tools + safe-hints servers).
- Separates tool impl from orchestration; Claude Code can consume directly.

### Permission System

User-in-control model:
- Approval + allowlist; show exact commands.
- Layers: risk detection → approval → audit → network blocking (configurable) → platform guardrails.

## Token/Latency Efficiency

- MCP-first, filtered defaults; avoid unbounded Bash.
- Previews/summaries to reduce output.
- Stdin mode stays single-turn; minimal context.

## Telemetry (opt-out)

- Controlled by `UATU_ENABLE_TELEMETRY` (default true) and `UATU_TELEMETRY_PATH` (default `~/.uatu/telemetry.jsonl`).
- Emits lightweight JSONL events for sessions (start/end), turns, and tool calls.
- Privacy guardrails: no user text, no full commands/outputs; only base command, flags, durations, status, and counts.
- Transport is local file today; emitter is noop when disabled.

## Current Architecture

**Project Structure (high level):**
```
uatu/
├── cli.py
├── chat_session/
│   ├── session.py
│   ├── handlers.py
│   └── commands.py
├── tools/
│   ├── __init__.py
│   ├── constants.py
│   └── safe_mcp.py
├── permissions.py
├── allowlist.py
├── network_allowlist.py
├── network_security.py
├── audit.py
├── ui/
│   ├── approval.py
│   ├── console.py
│   └── tool_preview.py
├── agents/__init__.py         # Subagents (cpu/mem, network, io, disk-space)
├── config.py
└── chat.py (compat wrapper)

tests/                         # ~150 tests
docs/
```

### High-Level Flow

```
           +---------------------------+
           |         CLI / REPL        |
           |  - interactive prompt     |
           |  - stdin one-shot         |
           +-------------+-------------+
                         |
                         v
              +-------------------+
              |   Chat Session    |
              | (session.py)      |
              | - run/run_oneshot |
              | - stats/budget    |
              +---+-----------+---+
                  |           |
                  |           v
                  |   +---------------+
                  |   |  Handlers     |
                  |   | (handlers.py) |
                  |   | - stream SDK  |
                  |   | - tool usage  |
                  |   | - previews    |
                  |   | - timing      |
                  |   +-------+-------+
                  |           |
                  v           v
        +----------------+   +-----------------+
        | Slash Commands |   | UI Layer        |
        | (commands.py)  |   | (console,       |
        | - /help, /clear|   |  approval,      |
        |   /allowlist   |   |  tool_preview)  |
        +-------+--------+   +-----------------+
                |
                v
        +----------------------+
        | Permissions & Safety |
        | (permissions,        |
        |  allowlist, network) |
        | - PreToolUse hooks   |
        | - approvals/allowlist|
        | - platform guardrails|
        +----------+-----------+
                   |
                   v
         +-----------------------+
         |   Subagents           |
         | (agents/__init__.py)  |
         | - cpu/mem, network,   |
         |   io, disk-space      |
         +----------+------------+
                    |
                    v
        +---------------------------+
        |        Tool Layer         |
        | - MCP system-tools server |
        | - MCP safe-hints server   |
        | - Bash tool (SDK)         |
        +-------------+-------------+
                      |
                      v
             +------------------+
             |  Target System   |
             |  (OS/processes/  |
             |   network/disk)  |
             +------------------+
```

