"""Bridge bcal's external-command protocol to bc_eval's CAPI OpenAI-compatible client."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import BinaryIO, cast

_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF_SEC = 2.0

_CERT_FILE_ENV = "CAPI_CERT_FILE"
_CERT_TENANT_ENV = "CAPI_TENANT_ID"
_CERT_CLIENT_ENV = "CAPI_CLIENT_ID"


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

    raise TypeError(f"Unsupported response type from bc_eval CAPI bridge: {type(value)!r}")


def _load_request(input_stream: BinaryIO) -> dict[str, object]:
    request_raw = json.loads(input_stream.read().decode("utf-8-sig"))
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    return cast(dict[str, object], request_raw)


def _create_with_retry(client: object, kwargs: dict[str, object]) -> object:
    # Retry transient CAPI failures (e.g. upstream OpenAI returns 5xx wrapped as DependencyFailure / server_error).
    from azure.core.exceptions import HttpResponseError

    last_exc: HttpResponseError | None = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            return client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
        except HttpResponseError as exc:
            last_exc = exc
            if attempt == _TRANSIENT_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_TRANSIENT_RETRY_BACKOFF_SEC * (2**attempt))
    assert last_exc is not None
    raise last_exc


def _patch_credential_from_local_file(cert_file: Path) -> None:
    """Avoid one Key Vault round-trip per LLM call by loading the CAPI client cert from disk.

    The bridge is spawned once per agent turn; the stock `CapiModel()` constructor calls
    `bc_eval.capi.capi_auth.get_certificate_credential()`, which hits Key Vault and AAD
    every time. With N parallel jobs * M turns this both rate-limits Key Vault and races
    on the local Azure CLI token cache (see analysis: `nl2al__trial-balance-diff-codeunit-1`
    in run 73481163213). When the prepare-workspace job has staged the PFX locally we
    monkey-patch the credential factory to read the same cert from disk.
    """
    import sys

    tenant_id = os.environ.get(_CERT_TENANT_ENV)
    client_id = os.environ.get(_CERT_CLIENT_ENV)
    if not tenant_id or not client_id:
        raise RuntimeError(f"{_CERT_FILE_ENV}={cert_file} requires {_CERT_TENANT_ENV} and {_CERT_CLIENT_ENV} to also be set.")

    import bc_eval.capi.capi_auth as capi_auth
    from azure.identity import CertificateCredential

    def _credential_from_file() -> CertificateCredential:
        return CertificateCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            certificate_path=str(cert_file),
        )

    # `bc_eval.capi.capi_model` (and possibly other modules) do
    # `from .capi_auth import get_certificate_credential` at import time, which
    # binds an independent reference in their own namespace. Patching only
    # `capi_auth.get_certificate_credential` doesn't update those bindings, so
    # the original Key-Vault-hitting function still runs from CapiModel.__init__.
    # Walk sys.modules and rebind every reference that points at the original.
    original = capi_auth.get_certificate_credential
    capi_auth.get_certificate_credential = _credential_from_file
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith("bc_eval"):
            continue
        if getattr(mod, "get_certificate_credential", None) is original:
            mod.get_certificate_credential = _credential_from_file


def _maybe_install_local_cert_credential() -> None:
    cert_path = os.environ.get(_CERT_FILE_ENV)
    if not cert_path:
        return

    cert_file = Path(cert_path)
    if not cert_file.is_file():
        raise RuntimeError(f"{_CERT_FILE_ENV}={cert_path} is set but the file does not exist.")

    _patch_credential_from_local_file(cert_file)


def main() -> int:
    request = _load_request(sys.stdin.buffer)
    model = request.get("model")
    messages = request.get("messages")
    if not isinstance(model, str):
        raise TypeError("External AI request requires a string model.")

    if not isinstance(messages, list):
        raise TypeError("External AI request requires a messages array.")

    try:
        from bc_eval.capi.capi_model import CapiModel
    except ImportError as exc:
        raise RuntimeError("bc-eval[capi] is required for the bcal CAPI bridge.") from exc

    _maybe_install_local_cert_credential()

    client = CapiModel()
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
    }
    if request.get("tools"):
        kwargs["tools"] = request["tools"]

    response = _create_with_retry(client, kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
