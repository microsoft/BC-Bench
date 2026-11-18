import hashlib
import json
from pathlib import Path
from typing import Self

from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from pydantic import JsonValue, TypeAdapter
from requests import PreparedRequest, Response

from bcbench.harms import write_json


class ServiceEvidence:
    """Verify judgment completeness before accepting the SDK's potentially defaulted verdict."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.events: list[dict[str, JsonValue]] = []
        self.provider = TracerProvider()
        self.instrumentor = RequestsInstrumentor()

    def __enter__(self) -> Self:
        self.directory.mkdir()
        if self.instrumentor.is_instrumented_by_opentelemetry:
            raise RuntimeError("Requests already instrumented; use a fresh process for private evaluation.")
        self.instrumentor.instrument(response_hook=self.record, tracer_provider=self.provider)
        return self

    def __exit__(self, *args: object) -> None:
        self.instrumentor.uninstrument()
        self.provider.shutdown()

    def record(self, span: object, request: PreparedRequest, response: Response) -> None:
        if "/sync_evals:run" not in (request.url or ""):
            return
        index = len(self.events)
        event: dict[str, JsonValue] = {"present": False}
        try:
            body = TypeAdapter(str | bytes).validate_python(request.body)
            (self.directory / f"{index:06d}.response").write_bytes(response.content)
            (self.directory / f"{index:06d}.request").write_bytes(body.encode("utf-8") if isinstance(body, str) else body)
            request_json = json.loads(body)
            payload = response.json()
            metric = request_json["testing_criteria"][0]["name"]
            source = request_json["data_source"]["source"]["content"]["item"]["response"]
            results = [result for result in payload.get("results", []) if result.get("name") == metric]
            result = results[0] if len(results) == 1 else {}
            event.update(
                metric=metric,
                response_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                present=response.status_code == 200
                and len(results) == 1
                and result.get("status") == "completed"
                and isinstance(result.get("passed"), bool)
                and isinstance(result.get("score"), (int, float))
                and not isinstance(result.get("score"), bool)
                and not result.get("error")
                and (result.get("properties") or {}).get("outcome") != "error"
                and not (payload.get("sample") or {}).get("error"),
            )
        except Exception as exc:  # noqa: BLE001 - hook failures explicitly invalidate scoring below; never use SDK defaults.
            # Hooks must retain failures: never let SDK missing-score defaults become successful judgments.
            event["inspection_error"] = type(exc).__name__
        self.events.append(TypeAdapter(dict[str, JsonValue]).validate_python(event))
        write_json(self.directory / "events.json", self.events)

    def confirms(self, response: str, metric: str) -> bool:
        digest = hashlib.sha256(response.encode("utf-8")).hexdigest()
        matches = [event for event in self.events if event.get("response_sha256") == digest and event.get("metric") == metric]
        return bool(matches) and all(event["present"] is True for event in matches) and all(event["present"] is True for event in self.events)
