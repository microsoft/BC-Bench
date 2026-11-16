"""Exact opt-in runtime identity; historical package admission is unchanged."""

from __future__ import annotations

import hashlib
import subprocess
import zipfile
from pathlib import Path

from bcal_reasoning_coding import AdmissionError, process_environment
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "experiments" / "bcal-reasoning-gold" / "package.json"


class PackagePin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^\d+\.\d+\.\d+\.\d+-beta$")
    source: str = Field(pattern=r"^[a-f0-9]{40}$")
    archive_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_files: int = Field(strict=True, gt=0)
    sdk_package: str
    sdk_runtime: str

    def discover(self, installed: Path, cache: Path) -> tuple[Path, Path]:
        binaries = [path for path in installed.rglob("bcal.dll") if path.parent.name == "any" and path.parent.parent.name == "net10.0"]
        name = f"microsoft.businesscentral.bcal.cli.{self.version}.nupkg"
        archives = list(installed.rglob(name))
        if (cache / name).is_file() and cache / name not in archives:
            archives.append(cache / name)
        if len(binaries) != 1 or not archives or any(hashlib.sha256(path.read_bytes()).hexdigest() != self.archive_sha256 for path in archives):
            raise AdmissionError("Exact new package discovery failed.")
        self.verify(binaries[0].parent, archives[0])
        return binaries[0].parent, archives[0]

    @property
    def product_version(self) -> str:
        return self.version.removesuffix("-beta") + "+" + self.source

    def verify(self, package: Path, archive: Path) -> int:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != self.archive_sha256:
            raise AdmissionError("Opt-in package archive hash differs.")
        expected = set()
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                prefix = "tools/net10.0/any/"
                if item.is_dir() or not item.filename.startswith(prefix):
                    continue
                relative = Path(item.filename[len(prefix) :])
                if relative.is_absolute() or ".." in relative.parts or relative in expected:
                    raise AdmissionError("Invalid or duplicate packaged payload path.")
                expected.add(relative)
                if hashlib.sha256(source.read(item)).digest() != hashlib.sha256((package / relative).read_bytes()).digest():
                    raise AdmissionError("Opt-in runtime payload differs from the archive.")
        if len(expected) != self.runtime_files or {path.relative_to(package) for path in package.rglob("*") if path.is_file()} != expected:
            raise AdmissionError("Opt-in runtime inventory has missing or extra files.")
        actual = subprocess.check_output([str(package / "bcal.exe"), "--version"], env=process_environment(), text=True, timeout=30).strip()
        if actual != self.product_version:
            raise AdmissionError("Opt-in executable version/source differs.")
        return len(expected)


def load_pin() -> PackagePin:
    return PackagePin.model_validate_json(PROFILE.read_bytes())
