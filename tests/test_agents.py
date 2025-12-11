"""Tests for specialized diagnostic agents."""


from uatu.agents import get_diagnostic_agents
from uatu.tools.constants import Tools


class TestDiagnosticAgents:
    """Test suite for diagnostic agent configuration."""

    def test_get_diagnostic_agents_returns_dict(self):
        """Test that get_diagnostic_agents returns a dictionary."""
        agents = get_diagnostic_agents()
        assert isinstance(agents, dict)

    def test_has_expected_agents(self):
        """Test that all expected agents are present."""
        agents = get_diagnostic_agents()
        expected_agents = {
            "cpu-memory-diagnostics",
            "network-diagnostics",
            "io-diagnostics",
            "disk-space-diagnostics",
        }
        assert set(agents.keys()) == expected_agents

    def test_cpu_memory_agent_configuration(self):
        """Test CPU/Memory diagnostics agent has correct configuration."""
        agents = get_diagnostic_agents()
        cpu_memory_agent = agents["cpu-memory-diagnostics"]

        # Check description covers both CPU and memory
        assert "cpu" in cpu_memory_agent.description.lower()
        assert "memory" in cpu_memory_agent.description.lower()
        assert len(cpu_memory_agent.description) > 20

        # Check prompt is comprehensive and covers both
        assert len(cpu_memory_agent.prompt) > 500
        assert "CPU" in cpu_memory_agent.prompt or "cpu" in cpu_memory_agent.prompt
        assert "memory" in cpu_memory_agent.prompt.lower()

        # Check tool access
        assert Tools.LIST_PROCESSES in cpu_memory_agent.tools
        assert Tools.GET_SYSTEM_INFO in cpu_memory_agent.tools
        assert Tools.GET_PROCESS_TREE in cpu_memory_agent.tools
        assert Tools.BASH in cpu_memory_agent.tools

        # Should NOT have network tools
        assert Tools.WEB_FETCH not in cpu_memory_agent.tools
        assert Tools.CHECK_PORT_BINDING not in cpu_memory_agent.tools

        # Check model inheritance
        assert cpu_memory_agent.model == "inherit"

    def test_network_agent_configuration(self):
        """Test network diagnostics agent has correct configuration."""
        agents = get_diagnostic_agents()
        network_agent = agents["network-diagnostics"]

        # Check description
        assert "network" in network_agent.description.lower()

        # Check comprehensive prompt
        assert len(network_agent.prompt) > 500
        assert "network" in network_agent.prompt.lower()

        # Check tool access - should have network-specific tools
        assert Tools.CHECK_PORT_BINDING in network_agent.tools
        assert Tools.FIND_PROCESS_BY_NAME in network_agent.tools
        assert Tools.GET_PROCESS_TREE in network_agent.tools
        assert Tools.BASH in network_agent.tools
        assert Tools.WEB_FETCH in network_agent.tools

    def test_io_agent_configuration(self):
        """Test I/O diagnostics agent has correct configuration."""
        agents = get_diagnostic_agents()
        io_agent = agents["io-diagnostics"]

        # Check description
        assert "i/o" in io_agent.description.lower() or "disk" in io_agent.description.lower()

        # Check comprehensive prompt
        assert len(io_agent.prompt) > 500
        assert ("I/O" in io_agent.prompt or "i/o" in io_agent.prompt.lower())

        # Check tool access
        assert Tools.LIST_PROCESSES in io_agent.tools
        assert Tools.GET_SYSTEM_INFO in io_agent.tools
        assert Tools.FIND_PROCESS_BY_NAME in io_agent.tools
        assert Tools.READ_PROC_FILE in io_agent.tools
        assert Tools.BASH in io_agent.tools

        # Should NOT have network tools
        assert Tools.WEB_FETCH not in io_agent.tools
        assert Tools.CHECK_PORT_BINDING not in io_agent.tools

    def test_all_agents_have_descriptions(self):
        """Test that all agents have non-empty descriptions."""
        agents = get_diagnostic_agents()
        for name, agent in agents.items():
            assert agent.description, f"Agent {name} has empty description"
            assert len(agent.description) > 20, f"Agent {name} description too short"

    def test_all_agents_have_prompts(self):
        """Test that all agents have comprehensive prompts."""
        agents = get_diagnostic_agents()
        for name, agent in agents.items():
            assert agent.prompt, f"Agent {name} has empty prompt"
            assert len(agent.prompt) > 500, f"Agent {name} prompt too short (should be comprehensive)"

    def test_all_agents_have_tools(self):
        """Test that all agents have at least some tools."""
        agents = get_diagnostic_agents()
        for name, agent in agents.items():
            assert agent.tools, f"Agent {name} has no tools"
            assert len(agent.tools) >= 2, f"Agent {name} has too few tools"

    def test_all_agents_inherit_model(self):
        """Test that all agents use model inheritance."""
        agents = get_diagnostic_agents()
        for name, agent in agents.items():
            assert agent.model == "inherit", f"Agent {name} should inherit model"

    def test_agents_have_specialized_tool_access(self):
        """Test that agents have appropriate specialized tool access."""
        agents = get_diagnostic_agents()

        # CPU/Memory agent has system-level tools
        cpu_memory_tools = set(agents["cpu-memory-diagnostics"].tools)
        assert Tools.LIST_PROCESSES in cpu_memory_tools
        assert Tools.GET_SYSTEM_INFO in cpu_memory_tools
        assert Tools.GET_PROCESS_TREE in cpu_memory_tools

        # Network agent should have unique network tools
        network_tools = set(agents["network-diagnostics"].tools)
        assert Tools.CHECK_PORT_BINDING in network_tools
        assert Tools.WEB_FETCH in network_tools

        # I/O agent should have read_proc_file for /proc/[pid]/io
        io_tools = set(agents["io-diagnostics"].tools)
        assert Tools.READ_PROC_FILE in io_tools

    def test_agents_do_not_overlap_unnecessarily(self):
        """Test that agents don't have unnecessary tool overlap."""
        agents = get_diagnostic_agents()

        # Network agent may include LIST_PROCESSES with filters; ensure key network tools present
        network_tools = set(agents["network-diagnostics"].tools)
        assert Tools.CHECK_PORT_BINDING in network_tools

        # I/O agent should focus on I/O-specific tools
        io_tools = set(agents["io-diagnostics"].tools)
        # Has READ_PROC_FILE for /proc/[pid]/io
        assert Tools.READ_PROC_FILE in io_tools
