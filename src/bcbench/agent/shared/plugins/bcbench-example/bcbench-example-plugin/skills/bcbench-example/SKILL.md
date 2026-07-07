---
name: bcbench-example
description: BC-Bench example skill — a no-op skill that only exists to prove the BC-Bench `plugins` experiment toggle installed a plugin into the agent's isolated config home and made its skill available. USE FOR nothing real; it is a smoke-test marker. DO NOT USE FOR actual Business Central / AL work.
---

# BC-Bench Example Skill

This skill is bundled by `bcbench-example-plugin` and does no real work. It
exists solely so that enabling the BC-Bench `plugins` experiment toggle has a
concrete, self-contained plugin to install — verifying end to end that a
marketplace is registered and a plugin is installed into the agent's per-entry
isolated config home (`COPILOT_HOME` / `CLAUDE_CONFIG_DIR`), and that its skill
loads.

If you are an agent and you can see this skill, the plugins toggle worked. Do
not invoke it for real tasks.
