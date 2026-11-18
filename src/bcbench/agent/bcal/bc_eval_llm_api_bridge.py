"""Bridge bcal's external-command protocol to bc_eval's M365 LLM API client."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_CERT_FILE_ENV = "LLM_API_CERTIFICATE_FILE"

# Separates the agent-under-test traffic from bc-eval's judge traffic (bc-eval's own agent host uses the same step).
_TAXONOMY_INFERENCE_STEP = "HostAgent"

_TOOLS_REASONING_EFFORT = "none"


def _to_jsonable(value: object) -> dict[str, object]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return cast(dict[str, object], dumped)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return cast(dict[str, object], dumped)

    if isinstance(value, dict):
        return cast(dict[str, object], value)

    raise TypeError(f"Unsupported response type from bc_eval LLM API bridge: {type(value)!r}")


def _load_request(input_stream: BinaryIO) -> dict[str, object]:
    request_raw = json.loads(input_stream.read().decode("utf-8-sig"))
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    return cast(dict[str, object], request_raw)


def _local_certificate_credential(tenant_id: str, client_id: str) -> TokenCredential | None:
    """Credential from a locally staged PFX, or None to let bc-eval sign through Key Vault.

    The bridge is spawned once per agent turn, so bc-eval's default credential would hit Key Vault
    and AAD on every turn; with N parallel jobs * M turns this rate-limits Key Vault.
    """
    cert_path = os.environ.get(_CERT_FILE_ENV)
    if not cert_path:
        return None

    cert_file = Path(cert_path)
    if not cert_file.is_file():
        raise RuntimeError(f"{_CERT_FILE_ENV}={cert_path} is set but the file does not exist.")

    from azure.identity import CertificateCredential

    # send_certificate_chain=True sends the x5c header (SNI auth), which the app registration
    # validates against; without it AAD returns AADSTS700027.
    return CertificateCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        certificate_path=str(cert_file),
        send_certificate_chain=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv or [])
    config = None
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if config["bc_eval_version"] != version("bc-eval"):
            raise ValueError("Installed bc-eval differs from the selected transport version.")
        if config["environment"] not in ("TEST", "PROD") or config["reasoning_effort"] not in ("none", "minimal", "low", "medium", "high", "xhigh"):
            raise ValueError("Explicit environment and supported reasoning effort are required.")

    request = _load_request(sys.stdin.buffer)
    model = request.get("model")
    messages = request.get("messages")
    if not isinstance(model, str):
        raise TypeError("External AI request requires a string model.")

    if not isinstance(messages, list):
        raise TypeError("External AI request requires a messages array.")

    try:
        from bc_eval.llm.llm_api import LlmApiSettings, create_llm_api_client
    except ImportError as exc:
        raise RuntimeError("bc-eval>=0.6.0 is required for the bcal LLM API bridge.") from exc

    settings = LlmApiSettings.from_env()
    if config is not None:
        if model != config["model"]:
            raise ValueError("BCal requested a different model than the configuration.")
        if request.get("reasoning_effort") not in (None, config["reasoning_effort"]):
            raise ValueError("BCal reasoning effort conflicts with the explicit configuration.")
        settings = replace(settings, environment=config["environment"])
    client = create_llm_api_client(
        inference_step=_TAXONOMY_INFERENCE_STEP,
        settings=settings,
        credential=_local_certificate_credential(settings.tenant_id, settings.client_id),
    )
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
        # bc-eval creates a new session per request; LLM API requires an empty ticket when none is cached.
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }
    tools = request.get("tools")
    if tools:
        kwargs["tools"] = tools
    reasoning_effort = request.get("reasoning_effort")
    if config is not None:
        reasoning_effort = config["reasoning_effort"]
    elif tools:
        reasoning_effort = _TOOLS_REASONING_EFFORT
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    response = client.chat.completions.create(**kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
