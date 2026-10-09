from pathlib import Path

import pytest

from bcbench.categories import category_definition
from bcbench.dataset import RepoGroundedEntry
from bcbench.types import EvaluationCategory


@pytest.mark.parametrize("category", list(EvaluationCategory))
def test_definition_belongs_to_its_category(category: EvaluationCategory):
    assert category_definition(category).category is category


def test_dataset_path_joins_the_dataset_dir():
    definition = category_definition(EvaluationCategory.CODE_REVIEW)

    assert definition.dataset_path(Path("data")) == Path("data") / "codereview.jsonl"


@pytest.mark.parametrize("category", list(EvaluationCategory))
def test_requires_repo_follows_the_entry_type(category: EvaluationCategory):
    definition = category_definition(category)

    assert definition.requires_repo is issubclass(definition.entry_type, RepoGroundedEntry)
