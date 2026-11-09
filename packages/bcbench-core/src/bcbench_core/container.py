"""Connection settings for a Business Central container."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerConfig:
    name: str
    username: str
    password: str
    company: str
    server_url: str = ""
    server_instance: str = ""
    mcp_url: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("Container name must not be empty")
        company = self.company.strip()
        if not company:
            raise ValueError("Company must not be empty")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "company", company)
