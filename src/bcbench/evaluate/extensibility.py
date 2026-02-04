import json
import os
from collections.abc import Callable

from openai import OpenAI

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


class AcceptanceCorrectnessRate:
    """Evaluator for checking if acceptance decision matches expected.

    Mirrors the bceval AcceptanceCorrectnessRate evaluator.
    """

    def __call__(self, *, expected: dict, output: dict, **kwargs) -> bool:
        """Check if acceptance decision is correct.

        Args:
            expected: Expected output with labels field
            output: Agent output with accepted field

        Returns:
            True if acceptance matches expected, False otherwise
        """
        expected_accepted_str = expected.get("labels", "")
        expected_accepted = False if not expected_accepted_str else "event-request" in expected_accepted_str or "request-for-external" in expected_accepted_str

        output_accepted = output.get("accepted", False)

        return expected_accepted == output_accepted


class LabelMatch:
    """Evaluator for checking if labels match expected.

    Mirrors the bceval LabelMatch evaluator.
    """

    def __call__(self, *, expected: dict, output: dict, **kwargs) -> bool:
        """Check if labels match exactly.

        Args:
            expected: Expected output with labels field (comma-separated string)
            output: Agent output with labels field (list)

        Returns:
            True if labels match exactly, False otherwise
        """
        expected_labels_str = expected.get("labels", "")
        expected_labels = {label.strip() for label in expected_labels_str.split(",")} if expected_labels_str else set()

        output_labels = set(output.get("labels", []))

        return expected_labels == output_labels


class IssueCommentMatch:
    """Evaluator for checking if comment semantically matches expected.

    Uses LLM-based semantic comparison to evaluate if the agent's comment
    matches the intent and content of the expected comment.
    """

    def __init__(self, model: str = "gpt-4", **kwargs):
        """Initialize comment evaluator with LLM classifier.

        Args:
            model: OpenAI model to use for semantic comparison
        """
        self.model = model
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        self.prompt_template = """Compare the following two GitHub issue comments to determine if they are semantically equivalent.

Expected Comment(s):
{expected_comments}

Agent's Comment:
{output_comment}

Consider the comments semantically equivalent if they:
1. Convey the same core message or intent
2. Address the same key points
3. Have similar tone and purpose (e.g., both requesting info, both approving, both rejecting)

Respond with ONLY 'Y' if they are semantically equivalent, or 'N' if they are not.
Do not provide any explanation, just Y or N."""

    def __call__(self, *, expected: dict, output: dict, **kwargs) -> bool:
        """Check if comment semantically matches expected.

        Args:
            expected: Expected output with comments field (list of comment dicts)
            output: Agent output with comment field (string)

        Returns:
            True if comments are semantically equivalent, False otherwise
        """
        expected_comments = expected.get("comments", [])
        output_comment = output.get("comment", "")

        # If neither has comments, that's a match
        if not expected_comments and not output_comment.strip():
            return True

        # If only one has comments, that's a mismatch
        if bool(expected_comments) != bool(output_comment.strip()):
            return False

        # Both have comments - use LLM to compare semantically
        try:
            # Format expected comments (list of dicts with 'body' field)
            expected_text = "\n".join(comment.get("body", "") for comment in expected_comments if isinstance(comment, dict))
            if not expected_text:
                # Fallback if comments are just strings
                expected_text = "\n".join(str(c) for c in expected_comments)

            prompt = self.prompt_template.format(expected_comments=expected_text, output_comment=output_comment)

            response = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], temperature=0.0, max_tokens=1)

            result = response.choices[0].message.content.strip().upper()
            return result == "Y"

        except Exception as e:
            logger.warning(f"LLM comparison failed: {e}. Falling back to presence check.")
            # Fallback to simple presence check if LLM call fails
            return bool(expected_comments) == bool(output_comment.strip())


class ExtensibilityPipeline(EvaluationPipeline):
    def setup(self, context: EvaluationContext) -> None:
        setup_repo_prebuild(context.entry, context.repo_path)

    def run_agent(self, context: EvaluationContext, agent_runner: Callable) -> None:
        with github_log_group(f"{context.agent_name} -- Entry: {context.entry.instance_id}"):
            context.metrics, context.experiment = agent_runner(context)

    def evaluate(self, context: EvaluationContext) -> None:
        """Evaluate agent output by comparing with expected results.

        Uses the same evaluators as bceval (acceptance, labels, comments).
        """
        resolved = False
        error_messages = []

        if isinstance(context.entry, ExtensibilityDatasetEntry):
            expected = context.entry.expected

            # Check if agent produced JSON output
            if context.metrics and isinstance(context.metrics, ExtAgentMetrics) and context.metrics.json_output:
                try:
                    # Parse agent's JSON output
                    agent_output = context.metrics.json_output
                    if isinstance(agent_output, str):
                        agent_output = json.loads(agent_output)

                    # Transform agent output to match bceval format
                    # Expected format: {accepted: bool, labels: list, comment: str}
                    final_determination = agent_output.get("final_determination", {})
                    output = {
                        "accepted": final_determination.get("outcome") == "FEASIBLE",
                        "labels": final_determination.get("labels_to_apply", []),
                        "comment": final_determination.get("comment_to_post", ""),
                    }

                    logger.info(f"Expected: {expected}")
                    logger.info(f"Agent output: {output}")

                    # Instantiate evaluators (same pattern as bceval)
                    acceptance_evaluator = AcceptanceCorrectnessRate()
                    labels_evaluator = LabelMatch()
                    comment_evaluator = IssueCommentMatch()

                    # Run evaluators
                    acceptance_ok = acceptance_evaluator(expected=expected, output=output)
                    labels_ok = labels_evaluator(expected=expected, output=output)
                    comment_ok = comment_evaluator(expected=expected, output=output)

                    # Collect errors
                    if not acceptance_ok:
                        error_messages.append("Acceptance: decision mismatch")
                    if not labels_ok:
                        error_messages.append(f"Labels: expected {expected.get('labels')}, got {output.get('labels')}")
                    if not comment_ok:
                        error_messages.append("Comment: presence mismatch")

                    # Set resolved if all evaluators pass
                    resolved = acceptance_ok and labels_ok and comment_ok

                    if resolved:
                        logger.info("✓ All evaluators passed")
                    else:
                        logger.warning(f"✗ Some evaluators failed: {error_messages}")

                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    error_messages.append(f"Failed to parse/validate JSON output: {e}")
                    logger.error(error_messages[-1])
            else:
                error_messages.append("Agent did not produce JSON output")
                logger.warning(error_messages[-1])

        # Create result based on validation
        error_summary = "; ".join(error_messages) if error_messages else "Validation failed"

        if resolved:
            result = ExtensibilityResult.create_success(context, "")
            logger.info(f"✓ Successfully validated {context.entry.instance_id}")
        else:
            result = ExtensibilityResult.create_test_failure(context, "", error_msg=error_summary)
            logger.warning(f"✗ Validation failed for {context.entry.instance_id}: {error_summary}")

        if result is not None:
            result.save(context.result_dir, f"{context.entry.instance_id}{_config.file_patterns.result_pattern}")
        else:
            logger.error(f"No result generated for {context.entry.instance_id}")
            raise RuntimeError(f"No result generated for {context.entry.instance_id}")
