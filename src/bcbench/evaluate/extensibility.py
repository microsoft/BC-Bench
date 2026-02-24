import json
import os
from collections.abc import Callable

from autoevals import LLMClassifier
from autoevals.score import Score

from bcbench.config import get_config
from bcbench.dataset import ExtensibilityDatasetEntry
from bcbench.evaluate.base import EvaluationPipeline
from bcbench.logger import get_logger, github_log_group
from bcbench.operations.setup_operations import setup_repo_prebuild
from bcbench.results.extensibility import ExtensibilityResult
from bcbench.types import EvaluationContext, ExtAgentMetrics

logger = get_logger(__name__)
_config = get_config()

__all__ = ["ExtensibilityPipeline"]


class IssueStateMatch:
    def __call__(self, *, expected: str, output: dict, **kwargs) -> bool:
        output_state = output["state_of_issue"]
        return expected == output_state


class LabelMatch:
    def __call__(self, *, expected: dict, output: dict, **kwargs) -> list[Score]:
        expected_labels_str = expected.get("labels", "")
        expected_labels = {label.strip() for label in expected_labels_str.split(",")} if expected_labels_str else set()
        output_labels = set(output.get("labels", []))

        matched_labels = expected_labels.intersection(output_labels)

        recall = (1.0 if len(output_labels) == 0 else 0.0) if len(expected_labels) == 0 else len(matched_labels) / len(expected_labels)
        precision = (1.0 if len(expected_labels) == 0 else 0.0) if len(output_labels) == 0 else len(matched_labels) / len(output_labels)
        f1_score = 0.0 if precision + recall == 0 else 2 * (precision * recall) / (precision + recall)

        match_rate = len(matched_labels) / len(expected_labels) if expected_labels else 0.0

        return [
            Score("LabelMatchRate", match_rate),
            Score("LabelRecall", recall),
            Score("LabelPrecision", precision),
            Score("LabelF1Score", f1_score),
        ]


def _create_github_models_client():
    import subprocess

    from openai import OpenAI

    token = os.environ.get("GITHUB_TOKEN") or subprocess.check_output(["gh", "auth", "token"], text=True).strip()

    return OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
    )


class IssueCommentMatch:
    def __init__(self, **kwargs):
        client = _create_github_models_client()
        self._classifier = LLMClassifier(
            name=self.__class__.__name__,
            model="openai/gpt-4.1",
            choice_scores={"Y": 1.0, "N": 0.0},
            client=client,
            prompt_template="""You are evaluating whether a *generated* GitHub BC extensibility issue comment is an acceptable
substitute for the *expected* comment, given the original issue.

Consider:
- Does the generated comment correctly address the same concern?
- Is it at least as helpful and specific as the expected one?
- Is it technically accurate w.r.t. the issue description?

Here is the data:
[Issue title]
{{input.title}}

[Issue body]
{{input.description}}

[Issue comments]
{{input.comments}}

[Expected comments]
{{expected.comments}}

[Model (generated) comment]
{{output.comment}}

Respond with a single letter:

Y - The model comment is an adequate replacement for the expected comment.
N - The model comment is not an adequate replacement.
""",
        )

    def __call__(self, *, input: str | dict, output: dict, expected: dict, **kwargs):
        return self._classifier(
            input=json.loads(input) if isinstance(input, str) else input,
            output=output,
            expected=expected,
            **kwargs,
        )


def compare_extensibility_output(
    entry: ExtensibilityDatasetEntry,
    metrics: ExtAgentMetrics | None,
    *,
    run_comment_eval: bool = True,
) -> tuple[bool, list[str]]:
    resolved = False
    error_messages: list[str] = []

    expected = entry.expected
    input_data = entry.get_task()

    if not metrics or not metrics.json_output:
        error_messages.append("Agent did not produce JSON output")
        logger.warning(error_messages[-1])
        return False, error_messages

    try:
        agent_output = metrics.json_output
        if isinstance(agent_output, str):
            agent_output = json.loads(agent_output)

        output = {
            "state_of_issue": agent_output.get("state_of_issue"),
            "labels": agent_output.get("labels_to_apply", []),
            "comment": agent_output.get("comment_to_post", ""),
        }

        logger.info(f"Expected: {expected}")
        logger.info(f"Agent output: {output}")

        # Issue state
        expected_state = expected.get("state", "open")
        state_ok = IssueStateMatch()(expected=expected_state, output=output)

        # Labels
        label_scores = LabelMatch()(expected=expected, output=output)
        for score in label_scores:
            logger.info(f"  {score.name}: {score.score}")
        label_f1 = next((s for s in label_scores if s.name == "LabelF1Score"), None)
        labels_ok = label_f1 is not None and label_f1.score == 1.0

        # Comment (LLM judge — may fail without API key)
        comment_ok = False
        comment_score = 0.0
        if run_comment_eval:
            try:
                comment_result = IssueCommentMatch()(input=input_data, expected=expected, output=output)
                comment_score = comment_result.score if comment_result else 0.0
                comment_ok = comment_score == 1.0
            except Exception as llm_err:
                logger.warning(f"IssueCommentMatch evaluator failed: {llm_err}")
                error_messages.append(f"Comment eval error: {llm_err}")
        else:
            logger.info("  CommentMatch: skipped (run_comment_eval=False)")
            comment_ok = True  # don't penalize when skipped

        logger.info(f"  CommentMatch: {comment_score}")

        # Collect errors
        if not state_ok:
            error_messages.append(f"IssueState: expected '{expected_state}', got '{output.get('state_of_issue')}'")
        if not labels_ok:
            error_messages.append(f"Labels: expected {expected.get('labels')}, got {output.get('labels')}")
        if not comment_ok and "Comment eval error" not in str(error_messages):
            error_messages.append(f"Comment: score {comment_score}")

        resolved = state_ok and labels_ok and comment_ok

        if resolved:
            logger.info("✓ All evaluators passed")
        else:
            logger.warning(f"✗ Some evaluators failed: {error_messages}")

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        error_messages.append(f"Failed to parse/validate JSON output: {e}")
        logger.error(error_messages[-1])

    return resolved, error_messages


class ExtensibilityPipeline(EvaluationPipeline):
    def setup(self, context: EvaluationContext) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        if isinstance(context.entry, ExtensibilityDatasetEntry):
            ext_metrics = context.metrics if isinstance(context.metrics, ExtAgentMetrics) else None
            resolved, error_messages = compare_extensibility_output(context.entry, ext_metrics)
        else:
            resolved, error_messages = False, ["Entry is not an ExtensibilityDatasetEntry"]

        # Extract json_output string for the result
        json_output_str: str | None = None
        if context.metrics and isinstance(context.metrics, ExtAgentMetrics):
            json_output_str = context.metrics.json_output

        # Create result based on validation
        error_summary = "; ".join(error_messages) if error_messages else "Validation failed"

        if resolved:
            result = ExtensibilityResult.create_success(context, "", json_output=json_output_str)
            logger.info(f"✓ Successfully validated {context.entry.instance_id}")
        else:
            result = ExtensibilityResult.create_test_failure(context, "", error_msg=error_summary, json_output=json_output_str)
            logger.warning(f"✗ Validation failed for {context.entry.instance_id}: {error_summary}")

        if result is not None:
            result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
        else:
            logger.error(f"No result generated for {context.entry.instance_id}")
            raise RuntimeError(f"No result generated for {context.entry.instance_id}")
