# Security Model

This document describes Uatu's security architecture, threat model, and design decisions around safe agent operation.

## Threat Model

### What We Protect Against

**1. Accidental Destructive Commands**
- Agent accidentally runs dangerous commands (`rm -rf`, `dd`, etc.)
- Misinterpreted user intent leading to data loss
- Unintended process termination

**2. Unauthorized System Modification**
- Agent making changes without user awareness
- Privilege escalation attempts
- System configuration changes

**3. Information Disclosure**
- Sensitive data in logs or investigation reports
- API keys, credentials exposed in command output
- Process information revealing private data

### What We Don't Protect Against

**Out of Scope**:
- Malicious users with legitimate access (if you have shell access, you can already do damage)
- Supply chain attacks on dependencies
- Physical security
- Network-level attacks

**Assumption**: The user running Uatu has legitimate system access and is authorized to perform system troubleshooting.

## Security Architecture

### Permission System

**Two-Layer Defense**:

1. **Tool-level permissions** - Which tools are available to the agent
2. **Command-level approval** - Runtime approval for potentially dangerous operations

#### Interactive Mode (Chat)

```
User → Agent → Tool Request → Permission Check → User Approval → Execute
```

**Behavior**:
- Bash commands require explicit approval (arrow-key prompt)
- User sees command before execution
- "Always allow" option adds to allowlist
- Can deny any command

**Security properties**:
- User has full visibility and control
- No surprises
- Allowlist builds over time for trusted workflows

#### Non-Interactive Modes (Investigate, Watch)

```
User → Agent → Tool Request → Permission Check → Auto-approve (if safe) → Execute
```

**Behavior**:
- `permission_mode="bypassPermissions"` in agent options
- Tools are pre-vetted for safety
- Read-only tools by default

**Security properties**:
- Tools are explicitly allowlisted in code
- No bash execution with arbitrary commands (uses MCP bash tool with controlled inputs)
- Write operations (like `kill_process`) are rare and logged

### Tool Architecture

**Primary Tool: Bash**
- Uatu uses bash commands as the primary investigation tool
- Provides maximum flexibility and power for system troubleshooting
- Familiar commands: `ps`, `top`, `df`, `netstat`, `lsof`, etc.

**Fallback: MCP Tools**
- Specialized read-only monitoring tools
- Used when bash is unavailable or blocked
- Tools: `get_system_info`, `list_processes`, `get_process_tree`, etc.

**Security Model**:

**Chat Mode** (Interactive):
- Bash commands require explicit user approval (permission prompts)
- User sees the actual command before execution
- Can build allowlist for trusted commands
- Set `UATU_READ_ONLY=true` to block all bash (forces MCP tools only)

**Investigate Mode** (One-Shot):
- Uses bash commands freely for diagnostics
- No interactive prompts (designed for automation)
- Read-only by nature (diagnostic commands only)

**Watch Mode** (Continuous):
- Heuristic detection doesn't use LLM (no tools needed)
- Optional investigations use bash for analysis
- Safe for 24/7 operation (observational commands)

**Design principle**: Empower the agent with bash (powerful and flexible), but with user control in interactive mode.

### Allowlist System

**Safe Commands** (always allowed):
```python
SAFE_BASE_COMMANDS = {
    "top", "ps", "df", "free", "uptime", "vm_stat", "vmstat",
    "iostat", "netstat", "lsof", "who", "w", "last",
    "dmesg", "journalctl",
}
```

These commands are read-only system monitoring tools. The list includes:
- Process monitoring: `top`, `ps`
- Resource usage: `df`, `free`, `vmstat`, `iostat`, `vm_stat` (macOS)
- Network: `netstat`, `lsof`
- Users: `who`, `w`, `last`
- Logs: `dmesg`, `journalctl`

**User-Defined Allowlist**:
- Stored in `~/.uatu/allowlist.json`
- Two types: base command or exact match
- User controls via `/allowlist` commands in chat mode

**Security properties**:
- Allowlist is per-user, not global
- Read-only commands prioritized
- User can audit and manage allowlist

### MCP Tool Security

**Why MCP is safer than raw bash**:
1. **Structured inputs**: Tools take typed parameters, not arbitrary strings
2. **Defined outputs**: Return structured data, not raw stdout
3. **Sandboxing potential**: MCP servers can run in containers
4. **Audit trail**: Tool calls are logged with parameters

**Current MCP tools**:
- All implemented in-process (no external MCP servers)
- Use Python's psutil (well-audited library)
- No shell execution in tool implementation

### Environment Configuration

**Read-Only Mode** (`UATU_READ_ONLY=true`):
- Disables all write operations
- Blocks `kill_process` tool
- Blocks bash commands (even with approval)
- Safe for production monitoring

**Require Approval** (`UATU_REQUIRE_APPROVAL=true`):
- Forces interactive approval for all bash commands
- Even in non-interactive modes
- Useful for sensitive environments

## Security by Operating Mode

### Chat Mode Security

**Access Control**:
- Interactive approval for every bash command
- User sees command before execution
- Can build allowlist over time

**Risks**:
- Social engineering: Agent convinces user to approve dangerous command
- User fatigue: Too many prompts → blind approval

**Mitigations**:
- Show actual command, not just description
- Default to "Deny"
- Allow granular allowlisting to reduce prompt fatigue

### Investigate Mode Security

**Access Control**:
- Read-only MCP tools only (no bash, no write operations)
- Allowed tools: `get_system_info`, `list_processes`, `get_process_tree`, `find_process_by_name`, `check_port_binding`, `read_proc_file`
- Runs with `bypassPermissions` (safe because all tools are read-only)
- Short-lived (single investigation)
- `UATU_REQUIRE_APPROVAL` does not apply (no risky operations available)

**Risks**:
- Malicious symptom input could trigger resource-intensive queries
- Information disclosure from process details

**Mitigations**:
- MCP tools have structured inputs (can't inject commands)
- All tools are read-only
- `read_proc_file` restricted to `/proc` and `/sys` paths only
- User reviews output before taking action
- Safety enforced by restricting `allowed_tools` to read-only operations

### Watch Mode Security

**Access Control**:
- Read-only MCP tools only (same as investigate mode)
- Allowed tools: `get_system_info`, `list_processes`, `get_process_tree`, `find_process_by_name`, `check_port_binding`, `read_proc_file`
- Optional LLM investigation uses `bypassPermissions` (safe because all tools are read-only)
- Long-running process (highest risk)
- `UATU_REQUIRE_APPROVAL` does not apply (no risky operations available)

**Risks**:
- Continuous operation → more attack surface
- Anomaly investigation could trigger resource-intensive queries
- Resource exhaustion (CPU/memory from monitoring itself)

**Mitigations**:
- Investigation is optional (`--investigate` flag)
- Watchers use minimal resources (heuristics only)
- Event log provides audit trail
- Can run with `UATU_READ_ONLY=true`

## Running Uatu Safely

### Recommended Configurations

**Development/Testing**:
```bash
# Full access, interactive approval
uatu  # Chat mode with approval prompts
```

**Production Monitoring**:
```bash
# Read-only continuous monitoring
UATU_READ_ONLY=true uatu watch --investigate
```

**Automation/CI**:
```bash
# Single investigation, read-only
UATU_READ_ONLY=true uatu investigate "high CPU usage"
```

### User Privileges

**Run as non-root when possible**:
- Most monitoring doesn't need root
- Process listing works for user's processes
- System metrics available to all users

**When root is needed**:
- Killing processes owned by other users
- Reading all process details
- Some systemd operations

**Best practice**: Run as non-root, elevate only when necessary.

### Container Deployment

**Docker considerations**:
```dockerfile
# Run as non-root user
USER uatu

# Read-only root filesystem
--read-only

# Drop capabilities
--cap-drop=ALL
--cap-add=SYS_PTRACE  # Only if needed for process inspection
```

**Security properties**:
- Limited blast radius
- Can't modify host system
- Isolated from other containers

## Logging & Audit Trail

**What gets logged**:
- All tool calls with parameters (`--log` in watch mode)
- Investigation results (`--investigation-log`)
- Bash command approvals/denials (in chat mode)
- Errors and exceptions

**Sensitive data handling**:
- Logs may contain process names, PIDs, resource usage
- Command arguments might contain sensitive data
- No automatic scrubbing (user responsibility)

**Recommendations**:
- Review logs before sharing
- Rotate logs regularly
- Restrict log file permissions (600)

## API Key Security

**Storage**:
- `.env` file in project directory (not committed)
- Environment variable `ANTHROPIC_API_KEY`
- No key storage in code or config files

**Transmission**:
- HTTPS to Anthropic API
- SDK handles secure transport

**Risks**:
- Key exposure in `.env` file
- Key in environment variables (visible to other processes)

**Mitigations**:
- `.env` in `.gitignore`
- Use restrictive file permissions (600)
- Consider secrets manager for production

## Known Limitations

### Current Gaps

1. **No rate limiting on tool calls**
   - Agent could call tools in tight loop
   - Resource exhaustion possible
   - Mitigation: Claude's built-in limits, max_turns setting

2. **Allowlist not encrypted**
   - Stored in plaintext JSON
   - Could be modified by other processes
   - Mitigation: File permissions (600)

3. **No sandboxing of MCP tools**
   - Tools run in same process as agent
   - Tool vulnerability = agent vulnerability
   - Mitigation: Use well-audited libraries (psutil)

4. **Investigation caching uses content hashing**
   - Similar anomalies get same cached response
   - Could miss subtle differences
   - Mitigation: Time-based cache expiry

### Future Enhancements

**Planned**:
- Audit mode: Log all tool calls without execution
- Dry-run mode: Show what would be executed
- Tool sandboxing: Run MCP tools in separate process
- Rate limiting: Max tools per minute
- Secret detection: Warn before logging potential secrets

## Responsible Disclosure

If you discover a security vulnerability in Uatu:

1. **Do not** open a public issue
2. Email: [Maintainer email from pyproject.toml]
3. Include: Description, steps to reproduce, impact assessment
4. Allow time for patch before public disclosure

## Security Checklist

Before deploying Uatu in production:

- [ ] Run as non-root user when possible
- [ ] Set `UATU_READ_ONLY=true` if no writes needed
- [ ] Secure `.env` file (chmod 600)
- [ ] Review allowlist regularly
- [ ] Rotate logs and restrict permissions
- [ ] Test in safe environment first
- [ ] Document approved use cases for your team
- [ ] Set up log monitoring/alerting
- [ ] Consider container deployment for isolation

## Philosophy

**"Trust but verify"**: Give agents capability, but with guardrails.

We believe AI agents should be:
1. **Transparent**: User sees what's happening
2. **Controllable**: User can approve/deny actions
3. **Auditable**: Complete log of what was done
4. **Safe by default**: Read-only unless explicitly authorized

The goal is empowerment, not automation for its own sake. The human remains in the loop.
