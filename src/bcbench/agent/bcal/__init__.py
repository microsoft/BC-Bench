"""BCal dotnet tool agent module for NL2AL evaluation."""

from bcbench.agent.bcal.agent import BCalBackendConfig, _resolve_bcal_executable, bcal_version, run_bcal_agent, run_bcal_prompt

resolve_bcal_executable = _resolve_bcal_executable

__all__ = ["BCalBackendConfig", "bcal_version", "resolve_bcal_executable", "run_bcal_agent", "run_bcal_prompt"]
