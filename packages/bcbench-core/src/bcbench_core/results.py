import json
import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EvaluationResult(BaseModel):
    instance_id: str

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self.model_dump(mode="json")) + "\n")

        logger.info("Saved evaluation result for %s to %s", self.instance_id, output_file)
