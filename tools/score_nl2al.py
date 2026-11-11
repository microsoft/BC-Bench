from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bc_eval.scorers.autoeval.lmchecklist import LmChecklist


def score_export(input_path: Path, output_path: Path, judge: LmChecklist, model: str) -> None:
    with input_path.open(encoding="utf-8-sig") as source, output_path.open("x", encoding="utf-8") as output:
        count = 0
        for line in source:
            row = json.loads(line)
            scores = judge.eval(input=row["input"], output=row["output"], expected=row["expected"], metadata=row["metadata"])
            output.write(
                json.dumps(
                    {
                        "judge_model": model,
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
    from bc_eval.scorers.autoeval.lmchecklist import LmChecklist

    client = create_llm_api_client().with_options(default_headers={"x-sticky-route-session-ticket": "opt-out"})
    score_export(args.input, args.output, LmChecklist(client=client), args.model)


if __name__ == "__main__":
    main()
