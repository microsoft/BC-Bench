import json
from autoevals import LLMClassifier
from autoevals.score import Score

class AcceptanceCorrectnessRate:
    def __call__(self, *, expected: dict, output: dict, **kwargs):
        expected_accepted_str = expected.get("labels", "")
        if not expected_accepted_str:
            exptected_accepted = False
        else:
            exptected_accepted = "event-request" in expected_accepted_str
        output_accepted = output.get("accepted", False)

        return exptected_accepted == output_accepted

class IssueCommentMatch:
    def __init__(self, **kwargs):
        self._classifier = LLMClassifier(
            name=__class__.__name__,
            model="gpt-41",
            choice_scores={"Y": 1.0, "N": 0.0},
            prompt_template="""
You are evaluating whether a *generated* GitHub BC extensibility issue comment is an acceptable
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
"""
        )

    def __call__(self, *, input: dict, output: dict, expected: dict, **kwargs):
        return self._classifier(
            input=json.loads(input),
            output=output,
            expected=expected,
            **kwargs)

class LabelMatch:
    def __call__(self, *, expected: dict, output: dict, **kwargs):
        expected_labels_str = expected.get("labels", "")
        if expected_labels_str:
            expected_labels = set(label.strip() for label in expected_labels_str.split(","))
        else:
            expected_labels = set()
        output_labels = set(output.get("labels", []))

        matched_labels = expected_labels.intersection(output_labels)

        # Calculate recall: matched / expected
        if len(expected_labels) == 0:
            recall = 1.0 if len(output_labels) == 0 else 0.0
        else:
            recall = len(matched_labels) / len(expected_labels)

        # Calculate precision: matched / output
        if len(output_labels) == 0:
            precision = 1.0 if len(expected_labels) == 0 else 0.0
        else:
            precision = len(matched_labels) / len(output_labels)

        # Calculate F1 score
        if precision + recall == 0:
            f1_score = 0.0
        else:
            f1_score = 2 * (precision * recall) / (precision + recall)

        # Calculate match rate
        match_rate = len(matched_labels) / len(expected_labels) if expected_labels else 0.0

        return [
            Score("LabelMatchRate", match_rate),
            Score("LabelRecall", recall),
            Score("LabelPrecision", precision),
            Score("LabelF1Score", f1_score),
        ]
