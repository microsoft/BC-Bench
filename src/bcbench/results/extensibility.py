from bcbench.results.base import BaseEvaluationResult


class ExtensibilityResult(BaseEvaluationResult):
    """Result class for extensibility evaluation category."""

    json_output: str | None = None

    # @classmethod
    # def from_json(cls, payload: dict[str, Any]) -> "ExtensibilityResult":
    #     return cls(
    #         instance_id=str(payload["instance_id"]),
    #         project=str(payload["project"]),
    #         model=str(payload["model"]),
    #         agent_name=str(payload["agent_name"]),
    #         resolved=bool(payload["resolved"]),
    #         build=bool(payload["build"]),
    #         generated_patch=payload.get("generated_patch", ""),
    #         error_message=payload.get("error_message"),
    #         agent_execution_time=payload.get("agent_execution_time"),
    #         agent_premium_requests=payload.get("agent_premium_requests"),
    #         number_of_steps=payload.get("number_of_steps"),
    #         prompt_tokens=payload.get("prompt_tokens"),
    #         completion_tokens=payload.get("completion_tokens"),
    #         mcp_servers=payload.get("mcp_servers"),
    #         custom_instructions=payload.get("custom_instructions"),
    #         json_output=payload.get("json_output"),
    #     )
