from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bc_eval.scorers.autoeval.lmchecklist import LmChecklist, Score
    from openai import OpenAI


class ChecklistResponseError(ValueError):
    def __init__(self, response: object, reason: str) -> None:
        super().__init__(reason)
        self.response = response


def validate_assertion_verdicts(evaluated: object, assertions: list[dict[str, Any]]) -> None:
    expected = [a["text"] for a in assertions]
    if not expected or any(not isinstance(text, str) or not text.strip() for text in expected) or len(set(expected)) != len(expected):
        raise ValueError("Expected assertions must have unique nonempty text.")
    if not isinstance(evaluated, list) or len(evaluated) != len(expected):
        raise ValueError("Judge must return exactly one verdict per expected assertion.")
    seen: set[str] = set()
    for verdict in evaluated:
        if not isinstance(verdict, dict) or not isinstance(verdict.get("text"), str) or verdict["text"] not in expected or verdict["text"] in seen:
            raise ValueError("Judge returned an unknown, duplicate or malformed assertion.")
        if type(verdict.get("pass")) is not bool:
            raise ValueError("Assertion pass must be a JSON Boolean.")
        reasoning = verdict.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip() or reasoning == "No evaluation returned":
            raise ValueError("Assertion judgment requires substantive reasoning.")
        seen.add(verdict["text"])


def create_checklist_judge(client: OpenAI) -> LmChecklist:
    from bc_eval.scorers.autoeval.lmchecklist import LmChecklist

    class ValidatedChecklist(LmChecklist):
        # bc-eval 0.6.1's parser fills missing verdicts and accepts truthy strings.
        def _process_response(self, resp: dict[str, Any], assertions: list[dict[str, Any]]) -> list[Score]:
            try:
                parsed = json.loads(resp["choices"][0]["message"]["content"])
                validate_assertion_verdicts(parsed["assertions"], assertions)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ChecklistResponseError(resp, str(exc)) from exc
            return super()._process_response(resp, assertions)

    return ValidatedChecklist(client=client)


def score_export(input_path: Path, output_path: Path, judge: LmChecklist, model: str) -> None:
    with input_path.open(encoding="utf-8-sig") as source, output_path.open("x", encoding="utf-8") as output:
        count = 0
        for line in source:
            row = json.loads(line)
            try:
                scores = judge.eval(input=row["input"], output=row["output"], expected=row["expected"], metadata=row["metadata"])
            except ChecklistResponseError as exc:
                output.write(json.dumps({"judge_model": model, "metadata": row["metadata"], "scores": [], "error": str(exc), "raw_judge_response": exc.response}) + "\n")
                output.flush()
                raise RuntimeError(f"Incomplete accuracy judging at row {count + 1}; raw judgment retained.") from exc
            output.write(
                json.dumps(
                    {
                        "judge_model": model,
                        "scorer_version": "nl2al-checklist-v2",
                        "metadata": row["metadata"],
                        "scores": [{"name": s.name, "score": s.score, "metadata": s.metadata} for s in scores],
                    }
                )
                + "\n"
            )
            output.flush()
            values = {s.name: s.score for s in scores}
            if (
                not {"test_passed", "critical_pass_rate", "pass_rate"} <= values.keys()
                or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values.values())
                or any(s.metadata and s.metadata.get("error") for s in scores)
            ):
                raise RuntimeError(f"Incomplete accuracy judging at row {count + 1}; partial output retained.")
            try:
                for score in scores:
                    validate_assertion_verdicts((score.metadata or {}).get("assertions"), row["expected"]["assertions"])
            except (ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f"Incomplete accuracy judging at row {count + 1}; invalid assertion verdicts retained.") from exc
            count += 1
        if not count:
            raise ValueError("Accuracy export is empty.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a saved NL2AL bceval export using the supported local bc-eval client.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="New JSONL path; existing results are never overwritten.")
    parser.add_argument("--model", default="gpt-56-ceres")
    args = parser.parse_args()
    os.environ["JUDGE_MODEL"] = args.model

    from bc_eval.llm.llm_api import create_llm_api_client

    client = create_llm_api_client().with_options(default_headers={"x-sticky-route-session-ticket": "opt-out"})
    score_export(args.input, args.output, create_checklist_judge(client), args.model)


if __name__ == "__main__":
    main()
