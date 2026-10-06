from __future__ import annotations

from typing import Annotated, override

from pydantic import Field

from bcbench.dataset.dataset_entry import BaseDatasetEntry


class DataQueryEntry(BaseDatasetEntry):
    """Dataset entry for the data-query category — answer a BC data question using the data tools.

    Execution-based: the agent retrieves the actual data (writing the rows to answer.json, plus the
    query it used to query.al); evaluation compares those rows to the entry's expected rows, computed
    on demand by running ``gold_query`` against the fixed Contoso container. The workspace is
    scaffolded by the pipeline, so there is no repo or commit.
    """

    nl_prompt: Annotated[str, Field(min_length=1, pattern=r"^[^\x00]*$")]
    gold_query: Annotated[str, Field(min_length=1, pattern=r"^[^\x00]*$")]
    # Whether row order is significant when comparing result sets (e.g. the question asks for a
    # specific ranking). Defaults to False: result sets are compared order-insensitively.
    ordered: bool = False

    @property
    @override
    def customization_profile(self) -> str:
        return "dataquery"

    @override
    def get_task(self) -> str:
        return self.nl_prompt

    @override
    def get_expected_output(self) -> str:
        return self.gold_query
