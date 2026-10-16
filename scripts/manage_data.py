#!/usr/bin/env python3
"""Explicit schema preparation and read-only business-data diagnostics."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from services.errors import SchemaError, ServiceError  # noqa: E402
from services.google_sheets import GoogleSheetsService  # noqa: E402
from services.operation_journal import json_text  # noqa: E402
from services.sheet_schema import typed_cell  # noqa: E402


def inspect_schema(service):
    result = {
        "spreadsheet_id": config.SPREADSHEET_ID,
        "sheets": {},
        "financial_writes": False,
    }
    existing = {ws.title: ws for ws in service.spreadsheet.worksheets()}
    for title, expected in config.DEFAULT_HEADERS.items():
        if title not in existing:
            result["sheets"][title] = {"missing_sheet": True}
            continue
        values = existing[title].get_all_values()
        headers = [str(h).strip() for h in values[0]] if values else []
        duplicates = [
            h for h, count in Counter(h for h in headers if h).items() if count > 1
        ]
        details = {
            "missing_headers": sorted(set(expected) - set(headers)),
            "duplicate_headers": duplicates,
            "nonempty_rows": sum(any(row) for row in values[1:]),
        }
        if title == config.SHEET_PHONES and "Telefon ID" in headers:
            index = headers.index("Telefon ID")
            ids = [
                str(row[index]).strip() if index < len(row) else ""
                for row in values[1:]
                if any(row)
            ]
            details["missing_phone_ids"] = ids.count("")
            details["duplicate_phone_ids"] = sum(
                count - 1 for key, count in Counter(ids).items() if key and count > 1
            )
        result["sheets"][title] = details
    return result


def missing_header_positions(headers, expected, missing):
    """Place each missing header next to its DEFAULT_HEADERS neighbour.

    Returns (final layout, [(header, column index)]) in insertion order; a header
    goes after the nearest earlier expected header, else before the nearest
    later one, else at the end.
    """
    layout = list(headers)
    placed = []
    for position, name in enumerate(expected):
        if name not in missing:
            continue
        earlier = [h for h in expected[:position] if h in layout]
        later = [h for h in expected[position + 1 :] if h in layout]
        if earlier:
            column = layout.index(earlier[-1]) + 1
        elif later:
            column = layout.index(later[0])
        else:
            column = len(layout)
        layout.insert(column, name)
        placed.append((name, column))
    return layout, placed


def schema_proposal(service, *, bootstrap=False):
    """Append only new identity/listing columns and ledger; never replace financial data."""
    existing = {ws.title: ws for ws in service.spreadsheet.worksheets()}
    requests, changes = [], []
    next_sheet_id = max((ws.id for ws in existing.values()), default=0) + 1
    for title, expected in config.DEFAULT_HEADERS.items():
        if title == config.SHEET_OPERATIONS and title not in existing:
            continue  # the operation ledger lives in the local SQLite journal
        if title not in existing:
            if not bootstrap:
                raise SchemaError(
                    f"{title}: dastlabki varaq mavjud emas; yangi baza uchun --bootstrap ishlating"
                )
            sheet_id = next_sheet_id
            next_sheet_id += 1
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "title": title,
                            "gridProperties": {
                                "rowCount": 100,
                                "columnCount": len(expected) + 5,
                            },
                        }
                    }
                }
            )
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                        "rows": [{"values": [typed_cell(name) for name in expected]}],
                        "fields": "userEnteredValue",
                    }
                }
            )
            changes.append(
                {"sheet": title, "action": "create_sheet", "headers": expected}
            )
            continue
        ws = existing[title]
        values = ws.get_all_values()
        headers = [str(h).strip() for h in values[0]] if values else []
        named = [h for h in headers if h]
        if len(named) != len(set(named)):
            raise SchemaError(f"{title}: takroriy sarlavha; avtomatik tuzatilmaydi")
        missing = [h for h in expected if h not in headers]
        allowed = (
            {"Telefon ID", "Elon narxi ($)"} if title == config.SHEET_PHONES else set()
        )
        if not headers and (bootstrap or title == config.SHEET_OPERATIONS):
            allowed = set(expected)
        if set(missing) - allowed:
            raise SchemaError(
                f"{title}: kutilmagan yetishmayotgan moliyaviy sarlavhalar; qo'lda tekshiring"
            )
        if missing and headers:
            # Insert real columns so existing data and formulas shift with them.
            new_headers, placed = missing_header_positions(headers, expected, missing)
            for name, column in placed:
                requests.append(
                    {
                        "insertDimension": {
                            "range": {
                                "sheetId": ws.id,
                                "dimension": "COLUMNS",
                                "startIndex": column,
                                "endIndex": column + 1,
                            },
                            "inheritFromBefore": column > 0,
                        }
                    }
                )
                requests.append(
                    {
                        "updateCells": {
                            "start": {
                                "sheetId": ws.id,
                                "rowIndex": 0,
                                "columnIndex": column,
                            },
                            "rows": [{"values": [typed_cell(name)]}],
                            "fields": "userEnteredValue",
                        }
                    }
                )
            changes.append(
                {
                    "sheet": title,
                    "action": "insert_headers",
                    "headers": [
                        {"header": name, "column": column} for name, column in placed
                    ],
                }
            )
        elif missing:
            new_headers = list(missing)
            if getattr(ws, "col_count", len(new_headers)) < len(new_headers):
                requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": ws.id,
                                "gridProperties": {"columnCount": len(new_headers) + 5},
                            },
                            "fields": "gridProperties.columnCount",
                        }
                    }
                )
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": ws.id,
                            "rowIndex": 0,
                            "columnIndex": len(headers),
                        },
                        "rows": [{"values": [typed_cell(h) for h in missing]}],
                        "fields": "userEnteredValue",
                    }
                }
            )
            changes.append(
                {"sheet": title, "action": "append_headers", "headers": missing}
            )
        else:
            new_headers = headers
        if title == config.SHEET_PHONES:
            id_column = new_headers.index("Telefon ID")
            # Rows were read before any column insert: existing IDs sit at the old index.
            old_id_column = headers.index("Telefon ID") if "Telefon ID" in headers else None
            current_ids = set()
            for row_index, row in enumerate(values[1:], start=2):
                if not any(row):
                    continue
                identity = (
                    str(row[old_id_column]).strip()
                    if old_id_column is not None and old_id_column < len(row)
                    else ""
                )
                if identity:
                    if identity in current_ids:
                        raise SchemaError(
                            f"Telefonlar:{row_index}: takroriy Telefon ID; avtomatik almashtirilmaydi"
                        )
                    current_ids.add(identity)
                    continue
                identity = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"oymaoy:{config.SPREADSHEET_ID}:{ws.id}:{row_index}",
                    )
                )
                if identity in current_ids:
                    raise SchemaError("Telefon ID migratsiyasida to'qnashuv")
                current_ids.add(identity)
                requests.append(
                    {
                        "updateCells": {
                            "start": {
                                "sheetId": ws.id,
                                "rowIndex": row_index - 1,
                                "columnIndex": id_column,
                            },
                            "rows": [{"values": [typed_cell(identity)]}],
                            "fields": "userEnteredValue",
                        }
                    }
                )
                changes.append(
                    {
                        "sheet": title,
                        "action": "assign_phone_id",
                        "row": row_index,
                        "phone_id": identity,
                    }
                )
    return {
        "spreadsheet_id": config.SPREADSHEET_ID,
        "financial_cells_changed": 0,
        "changes": changes,
        "batch": {"requests": requests},
    }


def parser():
    argument_parser = argparse.ArgumentParser(description=__doc__)
    commands = argument_parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "inspect", help="Read-only header and phone identity diagnostics"
    )
    prepare = commands.add_parser(
        "prepare", help="Preview schema changes; explicit --apply performs them"
    )
    prepare.add_argument(
        "--apply",
        action="store_true",
        help="Apply the printed schema batch to configured SPREADSHEET_ID",
    )
    prepare.add_argument(
        "--bootstrap",
        action="store_true",
        help="Create missing initial worksheets for a new spreadsheet",
    )
    commands.add_parser(
        "reconcile",
        help="Read-only financial totals and local journal recovery; no Google writes",
    )
    resolve = commands.add_parser(
        "resolve",
        help="Manual reconciliation after independently verifying the actual outcome",
    )
    resolve.add_argument("--operation-id", required=True)
    resolve.add_argument(
        "--outcome",
        choices=("not-applied", "notification-sent", "notification-not-sent"),
        required=True,
    )
    resolve.add_argument("--notification-index", type=int, default=0)
    resolve.add_argument(
        "--actor-id",
        type=int,
        required=True,
        help="Current active Admin/Hisobchi Telegram ID",
    )
    resolve.add_argument(
        "--channel-post-id",
        type=int,
        help="Independently verified delivered channel message ID",
    )
    resolve.add_argument(
        "--acknowledge-verified-outcome", action="store_true", required=True
    )
    return argument_parser


def main(argv=None):
    args = parser().parse_args(argv)
    config.load_runtime_config()
    if not config.SPREADSHEET_ID:
        raise SystemExit("SPREADSHEET_ID talab qilinadi")
    service = GoogleSheetsService()
    lock = None
    try:
        needs_journal = args.command in {"reconcile", "resolve"}
        needs_lock = needs_journal or (args.command == "prepare" and args.apply)
        if needs_lock:
            from services.runtime import WriterProcessLock

            lock = WriterProcessLock(str(config.OPERATION_DB_PATH) + ".lock")
            lock.acquire()
        # A read-only preview must not mutate the recovery journal of a running bot.
        service.initialize(open_journal=needs_journal)
        if args.command == "inspect":
            print(json_text(inspect_schema(service)))
        elif args.command == "prepare":
            proposal = schema_proposal(service, bootstrap=args.bootstrap)
            print(json.dumps(proposal, ensure_ascii=False, indent=2))
            if args.apply and proposal["batch"]["requests"]:
                # No blind retries: after a transport error inspect the schema before another --apply.
                service.spreadsheet.batch_update(proposal["batch"])
                service.readiness()
                print(
                    "Schema migratsiyasi tasdiqlandi. Moliyaviy kataklar o'zgartirilmadi."
                )
        elif args.command == "reconcile":
            service.readiness()
            result = {
                "operations": service.recover_pending_operations(),
                "reconciliation": service.get_reconciliation_report(),
                "notification_statuses": service.notification_statuses(),
                "google_writes": False,
            }
            try:
                result["financial_summary"] = service.get_financial_summary()
            except ServiceError as exc:
                result["financial_summary_error"] = str(exc)
            print(json_text(result))
            if (
                "financial_summary_error" in result
                or not result["reconciliation"]["ready"]
            ):
                return 1
        elif args.command == "resolve":
            service.readiness()
            if args.outcome == "not-applied":
                if args.channel_post_id is not None:
                    raise SchemaError("Bu natija uchun kanal post ID ishlatilmaydi")
                service.resolve_operation_not_applied(
                    args.operation_id, actor_id=args.actor_id
                )
            else:
                service.resolve_notification_outcome(
                    args.operation_id,
                    args.notification_index,
                    sent=args.outcome == "notification-sent",
                    actor_id=args.actor_id,
                    channel_post_id=args.channel_post_id,
                )
            print(
                json_text(
                    {
                        "operation_id": args.operation_id,
                        "manual_resolution": args.outcome,
                    }
                )
            )
        return 0
    except ServiceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print(
            "Google/mahalliy tekshiruv bajarilmadi. Shu buyruqni ko'r-ko'rona takrorlamang; avval holatni tekshiring.",
            file=sys.stderr,
        )
        return 1
    finally:
        service.close()
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
