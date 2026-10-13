"""Durable local intent, idempotency and notification delivery journal."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from services.errors import BusinessRuleError
from utils.money import to_cents


def _encode(value):
    if isinstance(value, Decimal):
        return {"_money_cents": to_cents(value)}
    raise TypeError(f"Unsupported journal value: {type(value).__name__}")


def _decode(value):
    if set(value) == {"_money_cents"}:
        return Decimal(value["_money_cents"]) / 100
    return value


def json_text(value) -> str:
    return json.dumps(
        value,
        default=_encode,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def from_json(value: str):
    return json.loads(value, object_hook=_decode)


def payload_hash(value) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        if self.path.is_file():
            self.path.chmod(0o600)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    batch TEXT NOT NULL,
                    result TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                        ('prepared','sending','committed','unknown','rejected')),
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    operation_id TEXT NOT NULL REFERENCES operations(operation_id),
                    notification_index INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN
                        ('pending','sending','sent','unknown')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(operation_id, notification_index)
                );
            """)
            # A process could have stopped immediately after either remote call.
            self.connection.execute(
                "UPDATE operations SET state='unknown', updated_at=? "
                "WHERE state='sending'",
                (utc_now(),),
            )
            self.connection.execute(
                "UPDATE notifications SET state='unknown' WHERE state='sending'"
            )
            try:
                self.cleanup_old_operations(retention_days=14)
            except Exception:
                pass

    def cleanup_old_operations(self, retention_days: int = 14):
        """Purge committed/rejected operations older than retention_days to keep local DB clean."""
        with self.connection:
            self.connection.execute(
                "DELETE FROM notifications WHERE operation_id IN "
                "(SELECT operation_id FROM operations WHERE state IN ('committed', 'rejected') "
                "AND datetime(created_at) < datetime('now', ?))",
                (f"-{int(retention_days)} days",),
            )
            self.connection.execute(
                "DELETE FROM operations WHERE state IN ('committed', 'rejected') "
                "AND datetime(created_at) < datetime('now', ?)",
                (f"-{int(retention_days)} days",),
            )

    def close(self):
        self.connection.close()

    def bind_source(self, spreadsheet_id):
        """A persistent journal belongs to exactly one Sheets database."""
        source = str(spreadsheet_id).strip()
        if not source:
            raise BusinessRuleError("Jurnal manbasi bo'sh bo'lmasin")
        with self.connection:
            row = self.connection.execute(
                "SELECT value FROM metadata WHERE key='spreadsheet_id'"
            ).fetchone()
            if row is not None and row["value"] != source:
                raise BusinessRuleError(
                    "Operatsiya jurnali boshqa Google jadvaliga bog'langan; alohida data volume ishlating"
                )
            self.connection.execute(
                "INSERT OR IGNORE INTO metadata (key,value) VALUES ('spreadsheet_id',?)",
                (source,),
            )

    def get(self, operation_id):
        row = self.connection.execute(
            "SELECT * FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("payload", "batch", "result"):
            result[key] = from_json(result[key])
        return result

    def prepare(
        self,
        operation_id,
        kind,
        actor_id,
        payload,
        digest,
        batch,
        result,
        notifications,
    ):
        existing = self.get(operation_id)
        if existing and existing["payload_hash"] != digest:
            raise BusinessRuleError("Bir amal ID bilan boshqa ma'lumot yuborilmasin")
        if existing and existing["state"] != "prepared":
            return existing
        now = utc_now()
        with self.connection:
            if existing:
                self.connection.execute(
                    "UPDATE operations SET batch=?,result=?,updated_at=? "
                    "WHERE operation_id=? AND state='prepared'",
                    (json_text(batch), json_text(result), now, operation_id),
                )
            else:
                self.connection.execute(
                    "INSERT INTO operations VALUES (?,?,?,?,?,?,?,'prepared','',?,?)",
                    (
                        operation_id,
                        kind,
                        str(actor_id),
                        digest,
                        json_text(payload),
                        json_text(batch),
                        json_text(result),
                        now,
                        now,
                    ),
                )
            for index, notification in enumerate(notifications):
                self.connection.execute(
                    "INSERT OR IGNORE INTO notifications "
                    "(operation_id,notification_index,payload,state) VALUES (?,?,?,'pending')",
                    (operation_id, index, json_text(notification)),
                )
        return self.get(operation_id)

    def transition(self, operation_id, state, error=""):
        allowed = {
            "prepared": {"sending", "committed", "rejected"},
            "sending": {"committed", "unknown", "rejected"},
            "unknown": {"committed", "rejected"},
            "committed": {"committed"},
            "rejected": {"rejected"},
        }
        row = self.get(operation_id)
        if row is None or state not in allowed[row["state"]]:
            raise BusinessRuleError("Amal holati o'tishi noto'g'ri")
        with self.connection:
            self.connection.execute(
                "UPDATE operations SET state=?,error=?,updated_at=? WHERE operation_id=?",
                (state, error, utc_now(), operation_id),
            )

    def unresolved(self):
        rows = self.connection.execute(
            "SELECT operation_id FROM operations WHERE state IN "
            "('unknown','sending') ORDER BY created_at"
        ).fetchall()
        return [self.get(row["operation_id"]) for row in rows]

    def pending_notifications(self):
        rows = self.connection.execute(
            "SELECT n.* FROM notifications n JOIN operations o "
            "ON n.operation_id=o.operation_id WHERE o.state='committed' AND n.state='pending' "
            "ORDER BY o.created_at,n.notification_index"
        ).fetchall()
        return [
            {
                "operation_id": row["operation_id"],
                "index": row["notification_index"],
                "payload": from_json(row["payload"]),
                "attempts": row["attempts"],
            }
            for row in rows
        ]

    def get_notification(self, operation_id, index):
        row = self.connection.execute(
            "SELECT operation_id,notification_index AS 'index',payload,state,attempts,error "
            "FROM notifications WHERE operation_id=? AND notification_index=?",
            (operation_id, index),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["payload"] = from_json(result["payload"])
        return result

    def outstanding_publications(self, phone_id, *, exclude_operation_id=None):
        # Match the decoded immutable payload, never names or mutable row numbers.
        rows = self.connection.execute(
            "SELECT n.operation_id,n.notification_index FROM notifications n JOIN operations o "
            "ON n.operation_id=o.operation_id WHERE n.state IN ('pending','sending','unknown') "
            "AND o.state!='rejected' ORDER BY o.created_at,n.notification_index"
        ).fetchall()
        result = []
        for row in rows:
            if row["operation_id"] == exclude_operation_id:
                continue
            item = self.get_notification(row["operation_id"], row["notification_index"])
            if (
                item["payload"].get("kind") == "publish_channel"
                and item["payload"].get("phone_id") == phone_id
            ):
                result.append(item)
        return result

    def mark_notification(
        self, operation_id, index, state, error="", *, reset_attempts=False
    ):
        allowed = {
            "pending": {"sending", "unknown"},
            "sending": {"sent", "pending", "unknown"},
            "unknown": {"sent", "pending"},
            "sent": {"sent"},
        }
        row = self.connection.execute(
            "SELECT state FROM notifications WHERE operation_id=? "
            "AND notification_index=?",
            (operation_id, index),
        ).fetchone()
        if row is None or state not in allowed[row["state"]]:
            raise BusinessRuleError("Bildirish holati o'tishi noto'g'ri")
        if reset_attempts and (row["state"] != "unknown" or state != "pending"):
            raise BusinessRuleError(
                "Urinishlar faqat tekshirilgan noaniq bildirishni tiklashda yangilanadi"
            )
        attempts = 1 if state == "sending" else 0
        with self.connection:
            self.connection.execute(
                "UPDATE notifications SET state=?,error=?,attempts=CASE WHEN ? THEN 0 ELSE attempts+? END "
                "WHERE operation_id=? AND notification_index=?",
                (state, error, reset_attempts, attempts, operation_id, index),
            )
