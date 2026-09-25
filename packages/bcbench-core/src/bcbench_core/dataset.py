"""Dataset types shared by evaluation applications."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class TestEntry(BaseModel):
    """Test methods to run in one test codeunit; field names match the dataset and PowerShell `TestEntry` format."""

    model_config = ConfigDict(frozen=True)

    codeunitID: Annotated[int, Field(gt=0)]
    functionName: Annotated[frozenset[str], Field(min_length=1)]

    @field_serializer("functionName")
    def _sorted_function_names(self, function_names: frozenset[str]) -> list[str]:
        # Sorted, so generated scripts and stored results are deterministic
        return sorted(function_names)
