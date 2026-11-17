import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from pydantic import JsonValue


def write_report(path: Path, sheets: dict[str, list[dict[str, JsonValue]]]) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        headers = list(dict.fromkeys(key for row in rows for key in row))
        sheet.append(headers)
        for row in rows:
            values = [json.dumps(value, ensure_ascii=False) if isinstance(value := row.get(header), (dict, list)) else value for header in headers]
            for value in values:
                if isinstance(value, str) and (len(value) > 32767 or ILLEGAL_CHARACTERS_RE.search(value)):
                    raise ValueError("Report cell exceeds Excel text limits or contains unsupported control characters. Raw JSONL/SDK results remain unchanged.")
            sheet.append(values)
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            sheet.column_dimensions[cell.column_letter].width = 35
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
    workbook.save(path)
