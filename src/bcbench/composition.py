import yaml

from bcbench.categories import CodeReviewCategory
from bcbench.config import Config


def create_code_review_category(config: Config) -> CodeReviewCategory:
    agent_config = yaml.safe_load((config.paths.agent_share_dir / "config.yaml").read_text(encoding="utf-8"))
    prompt_template = agent_config["prompt"]["code-review-template"]
    if not isinstance(prompt_template, str) or not prompt_template.strip():
        raise ValueError("Code-review prompt template must be a non-empty string")
    return CodeReviewCategory(
        dataset_path=config.paths.dataset_dir / "codereview.jsonl",
        prompt_template=prompt_template,
        judge_model=config.judge.code_review_model,
    )
