import pytest

from bcbench_core.container import ContainerConfig


class TestContainerConfig:
    def test_strips_name_and_company(self):
        container = ContainerConfig("  bcserver ", "admin", "secret", " CRONUS ")

        assert (container.name, container.company) == ("bcserver", "CRONUS")

    @pytest.mark.parametrize(("name", "company", "message"), [("  ", "CRONUS", "Container name"), ("bcserver", " ", "Company")])
    def test_rejects_blank_name_or_company(self, name, company, message):
        with pytest.raises(ValueError, match=message):
            ContainerConfig(name, "admin", "secret", company)
