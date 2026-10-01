import json
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class ResultWriter[R](Protocol):
    def write(self, result: R, output_dir: Path, filename: str) -> Path: ...


class JsonlResultWriter:
    def write(self, result: BaseModel, output_dir: Path, filename: str) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        with output_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result.model_dump(mode="json")) + "\n")
        return output_path
