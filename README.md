# Uatu - The Watcher

An agentic system troubleshooting tool powered by Claude. Chat with your system, investigate issues with AI-powered analysis, and autonomously monitor for anomalies.

## Why Uatu?

Traditional monitoring tools alert you to problems. Uatu **understands** them.


**Core capabilities:**
- Interactive chat mode for conversational system troubleshooting
- One-shot investigations for specific symptoms
- Continuous monitoring with adaptive baseline learning
- Root cause analysis connecting CPU, memory, processes, and logs
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

### Interactive Chat Mode (Default)

Start a conversational troubleshooting session:

```bash
uv run uatu
```

Ask questions naturally and get AI-powered analysis:
- "What's causing high CPU usage?"
- "Why is my server running slowly?"
- "Investigate recent memory issues"
- "Check for network bottlenecks"

### One-Shot Investigation

Investigate a specific symptom immediately:

```bash
uv run uatu investigate "server running slowly"
uv run uatu investigate "high CPU usage"
uv run uatu investigate "memory leak suspected"
```

The agent will:
- Gather relevant system information
- Analyze logs and metrics
- Provide root cause analysis
- Suggest actionable remediation steps

### Continuous Monitoring

Watch your system and detect anomalies autonomously:

```bash
# Fast testing (1 minute baseline)
uv run uatu watch --baseline 1

# Production monitoring (5 minute baseline, default)
uv run uatu watch

# With AI investigation of detected anomalies
uv run uatu watch --investigate
```

**How it works:**

**Phase 1: Detection** (default, no API calls)
- Establishes adaptive baseline by observing normal behavior
- Detects CPU spikes, memory issues, crash loops, process restarts
- Independent watchers run concurrently at optimal intervals
- Logs events to `~/.uatu/events.jsonl`

**Phase 2: Investigation** (--investigate flag)
- Uses Claude to investigate detected anomalies
- Explains root cause, impact, and relationships
- Provides actionable remediation steps with risk assessment
- Caches investigations to avoid redundant API calls
- Rate limits to control costs

View logged events:
```bash
uv run uatu events
uv run uatu events --last 20
```

## Configuration

Create `.env` with options:

```env
# Required
ANTHROPIC_API_KEY=your_key

# Optional
UATU_MODEL=claude-sonnet-4-5-20250929  # Claude model to use
UATU_READ_ONLY=true                     # Agent can only read, not modify system
UATU_REQUIRE_APPROVAL=true              # Require approval for risky actions
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
