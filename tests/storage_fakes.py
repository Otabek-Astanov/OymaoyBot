"""An atomic in-memory Sheets boundary; it never reaches a network."""

from copy import deepcopy
import re

import config


class FakeWorksheet:
    def __init__(self, title, sheet_id, headers, rows=()):
        self.title = title
        self.id = sheet_id
        self.values = [list(headers), *deepcopy(list(rows))]

    def row_values(self, row):
        if self.parent.read_failure == self.title:
            raise OSError("read failed")
        return deepcopy(self.values[row - 1])

    def get_all_values(self, **kwargs):
        if self.parent.read_failure == self.title:
            raise OSError("read failed")
        if kwargs.get("value_render_option") == "FORMULA":
            return deepcopy(self.values)
        return [
            [
                self.parent.computed_value(self, row_index, column_index, value)
                for column_index, value in enumerate(row)
            ]
            for row_index, row in enumerate(self.values)
        ]


class FakeSpreadsheet:
    def __init__(self):
        self.id = "offline-spreadsheet"
        headers = {k: list(v) for k, v in config.DEFAULT_HEADERS.items()}
        for name in ["Telefon ID", "Elon narxi ($)"]:
            if name not in headers[config.SHEET_PHONES]:
                headers[config.SHEET_PHONES].append(name)
        headers.setdefault(
            "Amallar",
            [
                "Operatsiya ID",
                "Amal turi",
                "Telegram foydalanuvchi ID",
                "Telefon ID",
                "Sana",
                "Natija",
                "Bildirish holati",
                "Bildirish ma'lumoti",
            ],
        )
        self.sheets = {
            title: FakeWorksheet(title, index, names)
            for index, (title, names) in enumerate(headers.items(), start=1)
        }
        for ws in self.sheets.values():
            ws.parent = self
        self.locale = "en_US"
        self.calls = []
        self.fail = None
        self.commit_then_fail = False
        self.read_failure = None
        self.add_record(
            config.SHEET_STAFF,
            {
                "Telegram ID": "1",
                "F.I.Sh": "Admin",
                "Roli": "Admin",
                "Holati": "Faol",
                "Jami KPI ($)": 0,
                "To'langan KPI ($)": 0,
                "Qoldiq KPI ($)": 0,
            },
        )

    def worksheet(self, title):
        if title == self.read_failure:
            raise OSError("read failed")
        return self.sheets[title]

    def worksheets(self):
        return list(self.sheets.values())

    def add_record(self, title, record):
        ws = self.sheets[title]
        ws.values.append([record.get(h, "") for h in ws.values[0]])

    def batch_update(self, body):
        self.calls.append(deepcopy(body))
        if self.fail and not self.commit_then_fail:
            raise self.fail
        values = {ws.id: deepcopy(ws.values) for ws in self.sheets.values()}
        for request in body["requests"]:
            if "appendCells" in request:
                part = request["appendCells"]
                table = values[part["sheetId"]]
                for row in part["rows"]:
                    table.append([self.cell_value(c) for c in row["values"]])
            elif "updateCells" in request:
                part = request["updateCells"]
                start = part["start"]
                table = values[start["sheetId"]]
                while len(table) <= start["rowIndex"]:
                    table.append([])
                row = table[start["rowIndex"]]
                while len(row) <= start["columnIndex"]:
                    row.append("")
                row[start["columnIndex"]] = self.cell_value(
                    part["rows"][0]["values"][0]
                )
            else:
                raise AssertionError(f"Unsupported request: {request}")
        for ws in self.sheets.values():
            ws.values = values[ws.id]
        if self.fail:
            raise self.fail
        return {"replies": [{} for _ in body["requests"]]}

    @staticmethod
    def cell_value(cell):
        return next(iter(cell["userEnteredValue"].values()))

    @staticmethod
    def column_index(letters):
        result = 0
        for letter in letters:
            result = result * 26 + ord(letter) - 64
        return result - 1

    def computed_value(self, ws, row_index, column_index, value):
        if not isinstance(value, str) or not value.startswith("="):
            return deepcopy(value)
        rounded = re.fullmatch(r"=ROUND\((.+)[,;]2\)", value)
        if rounded:
            return round(
                self.computed_value(
                    ws, row_index, column_index, "=" + rounded.group(1)
                ),
                2,
            )
        subtraction = re.fullmatch(r"=([A-Z]+)([0-9]+)-([A-Z]+)([0-9]+)", value)
        if subtraction:
            left, left_row, right, right_row = subtraction.groups()
            return float(ws.values[int(left_row) - 1][self.column_index(left)]) - float(
                ws.values[int(right_row) - 1][self.column_index(right)]
            )
        if value.startswith("=SUMIF("):
            partner = ws.values[row_index][ws.values[0].index("Hamkor nomi")]
            return sum(
                float(row.get("Hamkor qarzi ($)") or 0)
                for row in self.records("Telefonlar")
                if row.get("Hamkor nomi") == partner
            ) - sum(
                float(row.get("Summa ($)") or 0)
                for row in self.records("Kirimlar")
                if row.get("Hamkor nomi") == partner
            )
        # Formula injection tests read the raw value; this simulator does not execute it.
        return value

    def records(self, title):
        ws = self.sheets[title]
        return [dict(zip(ws.values[0], row)) for row in ws.values[1:] if any(row)]


def add_phone(
    spreadsheet,
    *,
    phone_id="phone-1",
    imei="000042",
    status="Sotuvda",
    cost=100,
    debt=0,
):
    spreadsheet.add_record(
        config.SHEET_PHONES,
        {
            "Telefon ID": phone_id,
            "IMEI": imei,
            "Brend": "iPhone",
            "Versiya": "14",
            "Holati": status,
            "Harid narxi ($)": cost,
            "Jami tannarx ($)": cost,
            "Harid to'lov turi": "Naqd" if not debt else "Qarz",
            "Harid qarz summasi ($)": debt,
            "Remont xarajati ($)": 0,
        },
    )
