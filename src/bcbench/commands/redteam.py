from bcbench.commands.harms import harms_app, run

# Preserve the redteam entrypoint without a second execution or reporting implementation.
redteam_app = harms_app
redteam_app.command("scan", hidden=True)(run)
