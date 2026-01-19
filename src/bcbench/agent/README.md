# Agent Implementations

```
agent/
├── shared/     # Shared code for claude and copilot (prompt, mcp, config)
├── claude/     # Claude Code
├── copilot/    # GitHub Copilot CLI
└── mini/       # mini-bc-agent (build on top of mini-swe-agent, different architecture)
```

- `shared/` contains unified prompt building, MCP configuration, and templates used by both Claude and Copilot
- `claude/` and `copilot/` contain CLI-specific invocation logic and metrics parsing
- `mini/` is architecturally different and remains separate
