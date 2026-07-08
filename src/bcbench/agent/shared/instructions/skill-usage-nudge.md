<!--
Ready-to-use skill-usage nudge for the `plugins` experiment.

WHY: installing a plugin makes its skills AVAILABLE but not USED. On well-specified
tasks (bug-fix, code-review) the agent usually works directly and never invokes a skill.
This subtle nudge reliably flips skill usage on without a heavy-handed "you MUST" directive.

HOW TO USE (per experiment arm):
  1. Append the "## Using your skills" block below to the target repo's canonical
     instructions file: src/bcbench/agent/shared/instructions/<owner>-<repo>/AGENTS.md
  2. Enable the instructions lever in src/bcbench/agent/shared/config.yaml:
         instructions:
           enabled: true
  3. Enable your plugin under `plugins:` in the same config.yaml.

This is an intervention: it is recorded on the result as `custom_instructions=True`,
so keep the wording subtle and account for it when attributing the plugin's effect.
Only the "## Using your skills" section below is meant to be copied — this comment is guidance.
-->

## Using your skills

You have optional skills available through the `skill` tool. When you start a task, briefly consider whether one of them fits — and if it does, use it.
