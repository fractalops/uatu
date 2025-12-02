# Uatu Internals

This document explains the architecture and implementation details of Uatu.

## Architecture Overview

### Two Operating Modes

**1. Interactive Chat Mode** (default: `uatu`)
- Long-lived conversation with maintained context
- Users ask questions, agent investigates, users follow up
- Built on stateful client with persistent conversation history
- Full tool access: MCP tools + Bash (with approval)

**2. Stdin Mode** (`echo "data" | uatu`)
- Single query with piped input data
- Stateless: process input, analyze, report, exit
- Optimized for log analysis, scripting, automation
- Same security model as interactive mode

### Core Components

#### Chat Session Layer (`uatu/chat_session/`)

The chat session manages both interactive and one-shot modes:

**`session.py`** - Core session management
- `run()`: Interactive loop with prompt_toolkit
- `run_oneshot()`: Single query from stdin
- Shared options, permissions, UI components
- Same security model for both modes

**`handlers.py`** - Message streaming
- Handles Claude SDK message streaming
- Tool usage display
- Response rendering with markdown

**`commands.py`** - Slash commands
- `/help`, `/exit`, `/allowlist` management
- Command parsing and execution

#### Tool Layer (`uatu/tools/`)

Tools are the agent's interface to the system via MCP:

**MCP Tools** (read-only):
- `get_system_info`: CPU, memory, load averages
- `list_processes`: Running processes with resource usage
- `get_process_tree`: Parent-child relationships
- `find_process_by_name`: Search for processes
- `check_port_binding`: What's using a port
- `read_proc_file`: Read from /proc filesystem

**Bash Tool** (requires approval):
- Flexible command execution for diagnostics
- Full shell access with permission system
- Used when MCP tools insufficient

**Design**: MCP tools for structured data, Bash for flexibility.

#### Permission System (`uatu/permissions.py`, `uatu/allowlist.py`)

**PreToolUse Hook**:
- Intercepts all tool calls before execution
- Bash commands require approval unless allowlisted
- Network tools (WebFetch/WebSearch) require domain approval
- MCP tools allowed by default (read-only)

**Risk Detection** (`allowlist.py`):
- CREDENTIAL_ACCESS_PATTERNS: SSH keys, API tokens, .env files
- DESTRUCTIVE_PATTERNS: rm -rf, dd, mkfs
- SYSTEM_MODIFICATION_PATTERNS: sudo, chmod, passwd
- SUSPICIOUS_PATTERNS: Piping to curl, base64 encoding

**Allowlist Management**:
- Base command allowlist (e.g., "ps" allows all ps variants)
- Exact match allowlist (specific command string)
- Persistent storage in ~/.config/uatu/allowlist.json

**Audit Logging** (`uatu/audit.py`):
- All approvals/denials logged
- SSRF protection events
- Network access decisions
- Allowlist modifications

#### UI Layer (`uatu/ui/`)

**`approval.py`** - Interactive approval prompts
- Arrow-key navigation
- Risk level display with warnings
- Syntax-highlighted commands
- "Allow once" / "Always allow" / "Deny" options

**`console.py`** - Reusable UI components
- Welcome messages
- Status indicators (✓ ✗ →)
- Tool usage display
- Error rendering

**`markdown.py`** - Custom markdown rendering
- Left-aligned headings
- Visual hierarchy (H1 with underlines, H2 with arrows)
- Consistent with "no fluff" philosophy

#### CLI Layer (`uatu/cli.py`)

Thin routing layer (69 lines, down from 398):
- Detects stdin mode vs interactive mode
- Builds prompt from stdin + optional query
- Delegates to ChatSession.run() or run_oneshot()
- Registers audit subcommand

## Key Technical Decisions

### MCP (Model Context Protocol)

MCP provides a standard way to expose system tools to LLMs:
- Tool definitions are portable across different agent frameworks
- Other tools can integrate with our MCP servers
- Claude Code can use our tools directly
- Separates tool implementation from agent orchestration

### Permission System

User approval + allowlist approach:
- Uatu needs real system access
- User is the security boundary
- Approval UX shows actual commands
- Allowlist enables automation

**Security layers**:
1. Risk detection (credential access, destructive ops)
2. User approval with context
3. Audit logging
4. Network command blocking (optional override)

## Token Efficiency

**Prompt Caching**:
- System prompt cached (1800+ lines)
- Tool definitions cached
- Only new messages sent to API

**Stdin Mode Optimization**:
- Single turn, no conversation accumulation
- Minimal context overhead
- Fast response for automation

## Current Architecture

**Project Structure**:
```
uatu/
├── cli.py                    # CLI routing (69 lines)
├── chat.py                   # Backward compatibility wrapper
├── chat_session/             # Chat implementation
│   ├── session.py            # Interactive + stdin modes
│   ├── handlers.py           # Message streaming
│   └── commands.py           # Slash commands
├── tools/                    # MCP tool implementations
│   ├── sdk_tools.py          # MCP server tools
│   ├── processes.py          # Process utilities
│   └── __init__.py           # Server creation
├── permissions.py            # PreToolUse hook
├── allowlist.py              # Command allowlist + risk detection
├── network_allowlist.py      # Domain allowlist
├── network_security.py       # SSRF protection
├── audit.py                  # Security audit logging
├── audit_cli.py              # Audit command
├── ui/                       # UI components
│   ├── approval.py           # Approval prompts
│   ├── console.py            # Reusable UI
│   └── markdown.py           # Markdown rendering
└── config.py                 # Settings

tests/                        # 103 unit tests
docs/                         # Documentation
```


## Testing Philosophy

**Test the boundaries**:
- Tool outputs are correct and parseable
- Permission system blocks/allows correctly
- Allowlist matching works as expected
- Risk detection catches dangerous patterns
- Network security blocks SSRF attempts

**Don't mock the LLM**:
- Agent behavior depends on LLM intelligence
- Integration tests more valuable than unit tests for agent logic
- Test tools and permissions independently

**Fast feedback**:
- `pytest` runs in less than a minute
- No external dependencies in unit tests

## Security

See [docs/security.md](security.md) for detailed security model, threat analysis, and safe deployment practices.
