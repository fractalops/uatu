# Uatu - The Watcher

An autonomous system troubleshooting agent powered by Claude. Continuously monitors server health, detects anomalies, diagnoses root causes, and provides actionable remediation steps.

## Why Uatu?

Traditional monitoring tools alert you to problems. Uatu understands them.

**Key capabilities:**
- Autonomous anomaly detection using adaptive baselines
- Root cause analysis connecting symptoms across CPU, memory, processes, and logs
- Natural language investigation interface for interactive troubleshooting
- Tiered tool discovery adapting to available system utilities
- Token-efficient caching and rate limiting for cost control

## Installation

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Configure API key
echo "ANTHROPIC_API_KEY=your_key" > .env
```

## Quick Start

### Interactive Chat Mode

Start a conversational troubleshooting session:

```bash
uv run uatu
```

Ask questions naturally:
- "What's causing high CPU usage?"
- "Why are there so many process crashes?"
- "Show me zombie processes"

### Continuous Monitoring

Watch your system and detect anomalies automatically:

```bash
# Async mode (recommended) - event-driven concurrent watchers
uv run uatu watch --async

# With LLM investigation of detected anomalies
uv run uatu watch --async --investigate

# Sync mode (legacy) - polling-based
uv run uatu watch --sync
```

**How it works:**

**Phase 1: Detection** (default, no API calls)
- Establishes adaptive baseline by observing normal behavior
- Detects CPU spikes, memory issues, crash loops, process restarts
- Independent watchers run concurrently at optimal intervals
- Logs events to `~/.uatu/events.jsonl`

**Phase 2: Investigation** (--investigate flag)
- Queues detected anomalies for LLM analysis
- Explains root cause, impact, and relationships
- Provides actionable remediation steps with risk assessment
- Caches investigations to avoid redundant API calls
- Rate limits to control costs

View logged events:
```bash
uv run uatu events
```

### One-Shot Investigation

Investigate a specific symptom immediately:

```bash
uv run uatu investigate "server running slowly"
```

### System Commands

No API key required:

```bash
# Health check
uv run uatu check

# Process analysis
uv run uatu processes --high-cpu
uv run uatu processes --high-memory
uv run uatu processes --zombies

# Tool discovery
uv run uatu tools
```

## Configuration

Create `.env` with options:

```env
# Required
ANTHROPIC_API_KEY=your_key

# Optional
UATU_MODEL=claude-sonnet-4-5-20250929
UATU_MAX_TOKENS=4096
UATU_TEMPERATURE=0.0
UATU_READ_ONLY=true
UATU_REQUIRE_APPROVAL=true
```

## Development

```bash
# Run tests (20 unit tests)
uv run pytest

# Lint
uv run ruff check .

# Format
uv run ruff format .
```

## Project Structure

```
uatu/
├── uatu/
│   ├── agent.py              # Claude Agent SDK integration
│   ├── chat.py               # Interactive chat interface
│   ├── cli.py                # Command-line interface
│   ├── config.py             # Settings management
│   ├── token_tracker.py      # Token usage tracking
│   ├── capabilities.py       # Tool discovery
│   ├── events/               # Event bus
│   │   └── bus.py
│   ├── tools/                # System analysis
│   │   ├── processes.py
│   │   ├── proc_tools.py
│   │   └── registry.py
│   └── watcher/              # Monitoring
│       ├── base.py           # Abstract interfaces
│       ├── models.py         # Data models
│       ├── async_core.py     # Async orchestration
│       ├── async_watchers.py # CPU, Memory, Process, Load watchers
│       ├── async_handlers.py # Event handlers
│       └── core.py           # Sync watcher (legacy)
└── tests/
    ├── conftest.py           # Test fixtures
    ├── test_event_bus.py
    ├── test_watchers.py
    ├── test_handlers.py
    └── test_processes.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
