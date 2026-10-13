import pytest
from pydantic import ValidationError

from bcbench.types import BCalPackageProvenance, BCalPackageSource


def test_official_package_is_master_from_the_official_feed():
    package = BCalPackageProvenance(source=BCalPackageSource.OFFICIAL, branch="master")

    assert package.feed_name == "DynamicsSMBPackages"
    assert not package.is_experiment


def test_experimental_package_uses_the_test_local_view():
    package = BCalPackageProvenance(source=BCalPackageSource.EXPERIMENT, branch="private/user/feature+experiment")

    assert package.feed_name == "DynamicsSMBTest@Local"
    assert package.is_experiment


@pytest.mark.parametrize(
    ("source", "branch"),
    [
        (BCalPackageSource.OFFICIAL, "main"),
        (BCalPackageSource.EXPERIMENT, "master"),
        (BCalPackageSource.EXPERIMENT, ""),
    ],
)
def test_invalid_source_branch_combinations_are_rejected(source, branch):
    with pytest.raises(ValidationError):
        BCalPackageProvenance(source=source, branch=branch)
