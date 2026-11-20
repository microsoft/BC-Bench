import pytest

pytest.importorskip("openpyxl")

from openpyxl import load_workbook

from bcbench.harms_report import write_report


def test_report_preserves_text_and_missing_sdk_judgments(tmp_path):
    path = tmp_path / "report.xlsx"
    write_report(path, {"Results": [{"Input": "=1+1", "Passed (SDK)": True}, {"Input": "A read-only balance indicator.", "Passed (SDK)": None, "Status": "missing"}]})
    with path.open("rb") as stream:
        workbook = load_workbook(stream)
        sheet = workbook["Results"]
        assert sheet["A2"].value == "=1+1"
        assert sheet["A2"].data_type == "s"
        assert sheet["B2"].value is True
        assert sheet["B3"].value is None
        assert sheet["C3"].value == "missing"


@pytest.mark.parametrize("text", ["x" * 32768, "text\x01"], ids=["too-long", "control-character"])
def test_report_rejects_unrepresentable_text_without_truncation(tmp_path, text):
    path = tmp_path / "report.xlsx"
    with pytest.raises(ValueError, match="Excel text limits"):
        write_report(path, {"Results": [{"Input": text}]})
    assert not path.exists()
