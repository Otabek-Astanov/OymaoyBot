"""Header-addressed reads and typed Google Sheets writes."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from services.errors import SchemaError
from utils.money import money_value


@dataclass(frozen=True)
class Formula:
    text: str


def records_with_rows(values: list[list[Any]]) -> list[dict]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    named = [name for name in headers if name]
    if len(named) != len(set(named)):
        raise SchemaError("Takroriy sarlavha mavjud")
    records = []
    for row_index, cells in enumerate(values[1:], start=2):
        if not any(value not in ("", None) for value in cells):
            continue
        record = {
            name: cells[index] if index < len(cells) else ""
            for index, name in enumerate(headers)
            if name
        }
        record["_row_index"] = row_index
        records.append(record)
    return records


def column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def typed_cell(value) -> dict:
    if isinstance(value, Formula):
        return {"userEnteredValue": {"formulaValue": value.text}}
    if isinstance(value, Decimal):
        amount = money_value(value, signed=True)
        return {"userEnteredValue": {"numberValue": float(amount)}}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": "" if value is None else str(value)}}


OPTIONAL_COLUMNS = {"Telefon ID", "Elon narxi ($)"}


@dataclass(frozen=True)
class SheetSchema:
    title: str
    sheet_id: int
    headers: tuple[str, ...]

    @classmethod
    def from_worksheet(cls, worksheet, expected: list[str]):
        headers = tuple(str(h).strip() for h in worksheet.row_values(1))
        named = [h for h in headers if h]
        if len(named) != len(set(named)):
            raise SchemaError(f"{worksheet.title}: takroriy sarlavha")
        missing = (set(expected) - OPTIONAL_COLUMNS) - set(named)
        if missing:
            raise SchemaError(
                f"{worksheet.title}: yetishmayotgan ustunlar: {', '.join(sorted(missing))}"
            )
        return cls(worksheet.title, worksheet.id, headers)

    def column(self, name: str) -> int:
        try:
            return self.headers.index(name)
        except ValueError as exc:
            raise SchemaError(f"{self.title}: {name} ustuni yo'q") from exc

    def letter(self, name: str) -> str:
        return column_letter(self.column(name) + 1)

    def append(self, values: dict) -> dict:
        cells = [typed_cell(values.get(name, "")) for name in self.headers]
        return {
            "appendCells": {
                "sheetId": self.sheet_id,
                "rows": [{"values": cells}],
                "fields": "userEnteredValue",
            }
        }

    def updates(self, row_index: int, values: dict) -> list[dict]:
        if row_index < 2:
            raise SchemaError("Sarlavha qatorini o'zgartirish taqiqlangan")
        requests = []
        for name, value in values.items():
            if name not in self.headers:
                continue
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": self.sheet_id,
                            "rowIndex": row_index - 1,
                            "columnIndex": self.column(name),
                        },
                        "rows": [{"values": [typed_cell(value)]}],
                        "fields": "userEnteredValue",
                    }
                }
            )
        return requests
