from __future__ import annotations

import json
import random as random_module
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict

from bcbench_core.exceptions import EntryNotFoundError


class DatasetEntry(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    instance_id: str

    @classmethod
    def load(cls, dataset_path: Path, entry_id: str | None = None, random: int | None = None) -> list[Self]:
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

        entries: list[Self] = []
        with dataset_path.open(encoding="utf-8") as file:
            for line in file:
                if not (stripped_line := line.strip()):
                    continue

                entry = cls.model_validate_json(stripped_line)
                if entry_id:
                    if entry.instance_id == entry_id:
                        return [entry]
                    continue
                entries.append(entry)

        if entry_id:
            raise EntryNotFoundError(entry_id)
        if random is not None and random > 0:
            return random_module.sample(entries, min(random, len(entries)))
        return entries

    def save_to_file(self, filepath: Path | str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            json.dump(self.model_dump(by_alias=True, mode="json"), handle, ensure_ascii=False)
            handle.write("\n")
