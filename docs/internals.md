# Uatu Internals

This document explains the architecture, design principles, and implementation details of Uatu.

## Design Principles

### Start Simple, Add Complexity When Needed

Uatu is built with a "simple first" approach. We don't build sophisticated systems for sophistication's sake—we build what's needed to solve the problem effectively. Each layer of complexity is justified by real requirements.

### Composability and Modularity

Components are designed to do one thing well and work together:
- **Tools** provide system introspection (CPU, memory, processes)
- **Detectors** identify anomalies using simple heuristics
- **Agents** orchestrate tools to investigate and diagnose
- **Watchers** coordinate monitoring over time

Each component can be tested, understood, and modified independently.

### Transparency Over Magic

Users see what's happening:
- Tool calls are displayed as they execute
- Bash commands show both description and actual command
- Investigations log findings and reasoning
- Token usage is tracked and reported

The agent's reasoning is part of the interface.

## Architecture Overview

### Three Operating Modes

**1. Interactive Chat Mode** (default: `uatu`)
- Long-lived conversation with maintained context
- Users ask questions, agent investigates, users follow up
- Built on stateful client with persistent conversation history

**2. One-Shot Investigation** (`uatu investigate`)
- Single symptom description → full diagnostic report
- Stateless: gather data, analyze, report, exit
- Optimized for automation and scripting

**3. Continuous Monitoring** (`uatu watch`)
- Autonomous system observation with baseline learning
- Heuristic anomaly detection (no LLM required for detection)
- Optional LLM investigation when anomalies exceed severity threshold
- Event-driven architecture with concurrent watchers

### Core Components

#### Agent Layer (`uatu/agent.py`, `uatu/chat.py`)

The agent orchestrates investigation using Claude via the Agent SDK. It:
- Uses Claude Code's system prompt for general capability
- Extends it with system troubleshooting expertise
- Has access to MCP tools for system introspection
- Manages conversation context (chat mode) or single turns (investigate mode)

#### Tool Layer (`uatu/tools/`)

Tools are the agent's interface to the system. They follow strict design rules:
- Read-only by default (observation before action)
- Clear, descriptive names and parameters
- Return structured data the LLM can reason about
- Implemented as MCP servers for interoperability

Current tools:
- `get_system_info`: CPU, memory, load averages
- `list_processes`: Running processes with resource usage
- `get_process_tree`: Parent-child relationships
- `kill_process`: Controlled process termination (requires approval)
- `bash`: Flexible command execution (requires approval)

**Future**: Agent skills will provide higher-level capabilities (log analysis, trace correlation, incident response patterns).

#### Watcher Layer (`uatu/watcher/`)

Watchers implement autonomous monitoring:

**Baseline Learning**
- Observe system for configurable period (default: 5 minutes)
- Calculate normal ranges for CPU, memory, process counts
- Establish what "healthy" looks like for this specific system

**Anomaly Detection** (`detector.py`)
- Heuristic-based (no LLM needed)
- Detects: CPU spikes, memory leaks, zombie processes, crash loops
- Multi-level severity: INFO, WARNING, ERROR, CRITICAL

**Investigation** (`investigator.py`)
- Optional LLM-powered root cause analysis
- Triggered only when anomalies exceed severity threshold
- Caching prevents repeated investigation of same issue
- Full agent capability: correlates metrics, checks logs, analyzes trends

**Event-Driven Architecture** (`async_*.py`)
- Multiple concurrent watchers (CPU, memory, processes)
- Pub/sub event bus for coordination
- Non-blocking: investigation doesn't delay detection
- Scales to many watchers without resource waste

#### Permission System (`uatu/permissions.py`, `uatu/allowlist.py`)

Bash commands require explicit approval unless allowlisted:
- Interactive prompts in chat mode
- Auto-approve in non-interactive mode (investigate, watch)
- Allowlist supports base commands (e.g., `ps`) and exact matches
- Safe commands (read-only) allowlisted by default

**Philosophy**: Trust but verify. Give agents capability, but with guardrails.

## Key Technical Decisions

### Why MCP (Model Context Protocol)?

MCP provides a standard way to expose system tools to LLMs:
- Tool definitions are portable across different agent frameworks
- Other tools can integrate with our MCP servers
- Claude Code can use our tools directly
- Separates tool implementation from agent orchestration

### Why Heuristic Detection + Optional LLM Investigation?

**Detection must be fast and as free ($) as we can**:
- Running an LLM every 10 seconds is costly and slow
- Most observations are normal—no investigation needed
- Deterministic math (baseline + threshold) catches 90% of issues

**Investigation should be thorough**:
- When anomaly detected, LLM provides deep analysis
- Correlates multiple signals, checks logs, explains causation
- Caching prevents redundant investigation of recurring issues

This hybrid approach balances cost, speed, and intelligence.

### Event-Driven


We use an event bus:
```python

async def cpu_watcher():
    while True:
        snapshot = await get_cpu()
        if anomaly: bus.publish(event)

async def memory_watcher():
    # Runs concurrently, independently
```

- Watchers run independently at their own intervals
- Investigation doesn't block detection

## Token Efficiency

**Prompt Caching**
- System prompt and tool definitions cached
- Baseline state cached during monitoring

**Investigation Triggers**
- Severity thresholds prevent investigation of minor anomalies
- Caching deduplicates recurring issues

**Context Management**
- One-shot mode: minimal context, single turn
- Chat mode: context accumulates but stays relevant
- Watch mode: investigation context isolated per event

## Future: Agent Skills

Skills will provide reusable, higher-level agent capabilities:

**Planned Skills**:
- `diagnose-crash-loop`: Pattern recognition for restart cycles
- `analyze-logs`: Structured log parsing and correlation
- `trace-bottleneck`: Follow request path through system
- `incident-response`: Guided remediation workflows

Skills are agent programs—they use tools, make decisions, and coordinate subtasks. They're invoked by name and compose like functions.

**We will add Skills to give the model high level capabilities**
- Encode expert knowledge and domain expertise as reusable components

## Development Workflow

**Running locally**:
```bash
uv sync                    # Install dependencies
uv run uatu                # Run interactive mode
uv run pytest              # Run tests
```

**Project Structure**:
```
uatu/
├── agent.py              # Core agent orchestration
├── chat.py               # Interactive chat interface
├── cli.py                # Command-line interface
├── tools/                # MCP tool implementations
├── watcher/              # Monitoring system
│   ├── detector.py       # Heuristic anomaly detection
│   ├── investigator.py   # LLM-powered analysis
│   ├── async_*.py        # Event-driven watchers
│   └── models.py         # Data structures
├── permissions.py        # Approval system
└── allowlist.py          # Command allowlist

tests/                    # Unit tests
docs/                     # Documentation
```

## Testing Philosophy

**Test the boundaries**:
- Tool outputs are correct and parseable
- Anomaly detection thresholds work as expected
- Permission system blocks/allows correctly
- Event bus handles concurrent operations

**Don't mock the LLM**:
- Agent behavior depends on LLM intelligence
- Integration tests more valuable than unit tests for agent logic
- Test tools independently, agent integration manually

**Fast feedback**:
- `pytest` runs in seconds
- No external dependencies in unit tests
- Watch mode has fast-test flag (`--baseline 1`)

## Known Limitations & Future Improvements

### Baseline Learning
**Current**: Fixed 5-minute learning period, static thresholds

**Limitations**:
- Doesn't account for time-of-day patterns (3am vs 3pm traffic)
- Doesn't adapt to weekly cycles (weekday vs weekend)
- Short baseline may miss periodic spikes

**Future improvements**:
- Adaptive baselines that update over time
- Time-windowed baselines (hourly, daily, weekly)
- Seasonal pattern detection

### Error Handling
**Current**: Basic exception handling, errors logged to console

**Future improvements**:
- Structured error logging with severity levels
- Graceful degradation when tools fail
- Retry logic with exponential backoff for API calls
- Circuit breaker for repeated failures

### Observability
**Current**: Token usage tracking, event logs, investigation logs

**Future improvements**:
- Structured logging (JSON format)
- Cost tracking per investigation
- Performance metrics (tool call latency, investigation duration)
- Alerting on agent failures

### Multi-System Support
**Current**: Single-system monitoring only

**Future improvements**:
- Monitor multiple systems from central Uatu instance
- Distributed watchers reporting to central aggregator
- Cross-system correlation (issue on server A causes issue on server B)

### Skills Architecture
**Current**: Planned, not yet implemented

**Design considerations**:
- Skills as Python modules vs LLM prompts vs hybrid approach
- Skill composition: Can skills call other skills?
- Security model: How to validate community-contributed skills?
- Testing: Unit tests for skills, integration tests for skill composition
- Distribution: Package skills separately or bundle with core?

**First skills to implement** (validates the abstraction):
- `diagnose-crash-loop`: Learn from this implementation
- `analyze-logs`: Tests file I/O and parsing patterns

## Security

See [docs/security.md](security.md) for detailed security model, threat analysis, and safe deployment practices.


"The best code is code that's easy to delete when requirements change."
