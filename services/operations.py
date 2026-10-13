"""One remotely atomic financial batch, with durable local intent first."""

from uuid import UUID

from services.errors import (
    AccessDenied,
    BusinessRuleError,
    OutcomeUnknown,
    StorageReadError,
    StorageWriteError,
)
from services.operation_journal import from_json, json_text, payload_hash


class OperationCoordinator:
    def __init__(self, service, journal):
        self.service = service
        self.journal = journal

    def remote_operation(self, operation_id):
        if not self.service._has_sheet("Amallar"):
            return None
        matches = [
            row
            for row in self.service._read("Amallar")
            if str(row.get("Operatsiya ID", "")) == operation_id
        ]
        if len(matches) > 1:
            raise BusinessRuleError("Amallar jurnalida takroriy operatsiya ID mavjud")
        return matches[0] if matches else None

    def reconcile(self, operation):
        row = self.remote_operation(operation["operation_id"])
        if row:
            try:
                meta = from_json(row["Bildirish ma'lumoti"])
            except (KeyError, ValueError, TypeError) as exc:
                raise BusinessRuleError(
                    "Amallar jurnalining metama'lumoti noto'g'ri"
                ) from exc
            if (
                meta.get("payload_hash") != operation["payload_hash"]
                or row.get("Natija") != "Yakunlandi"
            ):
                raise BusinessRuleError(
                    "Amallar jurnalidagi ma'lumot bilan mahalliy jurnal mos emas"
                )
            try:
                self.service._verify_batch(operation["batch"])
            except StorageReadError:
                return False
            self.journal.transition(operation["operation_id"], "committed")
            self.service.reload_cache()
            return True
        else:
            try:
                self.service._verify_batch(operation["batch"])
                self.journal.transition(operation["operation_id"], "committed")
                self.service.reload_cache()
                return True
            except Exception:
                return False

    def recover(self):
        recovered, quarantined = [], []
        for operation in self.journal.unresolved():
            (recovered if self.reconcile(operation) else quarantined).append(
                operation["operation_id"]
            )
        return {"recovered": recovered, "quarantined": quarantined}

    def run(self, operation_id, kind, actor_id, payload, notifications, builder):
        if (
            isinstance(actor_id, bool)
            or not str(actor_id).isascii()
            or not str(actor_id).isdigit()
            or int(actor_id) <= 0
        ):
            raise AccessDenied("Telegram foydalanuvchi ID noto'g'ri")
        actor_id = int(actor_id)
        try:
            if str(UUID(str(operation_id))) != str(operation_id):
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise BusinessRuleError("Amal ID haqiqiy UUID bo'lishi kerak") from exc
        # A retry must re-use the same business input, including actor and outbox.
        intent = {
            "kind": kind,
            "actor_id": str(actor_id),
            "data": payload,
            "notifications": list(notifications),
        }
        digest = payload_hash(intent)
        existing = self.journal.get(operation_id)
        if existing:
            if existing["payload_hash"] != digest:
                raise BusinessRuleError(
                    "Bir amal ID bilan boshqa ma'lumot yuborilmasin"
                )
            if existing["state"] == "committed":
                return existing["result"]
            if existing["state"] in {"unknown", "sending"}:
                if self.reconcile(existing):
                    return existing["result"]
                raise OutcomeUnknown(operation_id)
            if existing["state"] == "rejected":
                raise StorageWriteError(
                    "Amal rad etilgan. Tekshirishdan keyin yangi amal yarating."
                )
        if self.journal.unresolved():
            self.recover()
            unresolved = self.journal.unresolved()
            if unresolved:
                raise OutcomeUnknown(unresolved[0]["operation_id"])
        # Also prevents a replay after restoring an older local backup.
        remote = self.remote_operation(operation_id)
        if remote:
            try:
                meta = from_json(remote["Bildirish ma'lumoti"])
            except (KeyError, ValueError, TypeError) as exc:
                raise BusinessRuleError(
                    "Amallar jurnalining metama'lumoti noto'g'ri"
                ) from exc
            if meta.get("payload_hash") != digest:
                raise BusinessRuleError("Amal ID mavjud, ammo uning ma'lumoti boshqa")
            result = meta["result"]
            self.journal.prepare(
                operation_id, kind, actor_id, intent, digest, {}, result, notifications
            )
            self.journal.transition(operation_id, "committed")
            # Delivery may have succeeded before the local backup: do not resend it blindly.
            for index, _ in enumerate(notifications):
                self.journal.mark_notification(operation_id, index, "unknown")
            return result
        self.service._authorize(actor_id, kind)
        built = builder()
        requests, result, phone_id = built[:3]
        metadata = built[3] if len(built) > 3 else {}
        ledger = {
            "Operatsiya ID": operation_id,
            "Amal turi": kind,
            "Telegram foydalanuvchi ID": str(actor_id),
            "Telefon ID": phone_id,
            "Sana": self.service._now(),
            "Natija": "Yakunlandi",
            "Bildirish holati": "Kutilmoqda" if notifications else "Talab qilinmaydi",
            "Bildirish ma'lumoti": json_text(
                {
                    "payload_hash": digest,
                    "result": result,
                    "notifications": list(notifications),
                    **metadata,
                }
            ),
        }
        if self.service._has_sheet("Amallar"):
            requests.append(self.service._schema("Amallar").append(ledger))
        batch = {"requests": requests}
        self.journal.prepare(
            operation_id, kind, actor_id, intent, digest, batch, result, notifications
        )
        self.journal.transition(operation_id, "sending")
        try:
            self.service.spreadsheet.batch_update(batch)
        except Exception as exc:
            response = getattr(exc, "response", None)
            code = getattr(response, "status_code", None)
            if code is None:
                code = getattr(getattr(exc, "resp", None), "status", None)
            if isinstance(code, int) and 400 <= code < 500 and code not in {408, 409}:
                self.journal.transition(operation_id, "rejected", f"Sheets HTTP {code}")
                raise StorageWriteError(
                    "Google yozuvni rad etdi; hech qanday moliyaviy commit tasdiqlanmadi"
                ) from exc
            self.journal.transition(
                operation_id, "unknown", "Sheets javobi tasdiqlanmadi"
            )
            raise OutcomeUnknown(operation_id) from exc
        self.service.reload_cache()
        try:
            self.service._verify_batch(batch)
            self.journal.transition(operation_id, "committed")
        except Exception as exc:
            # The Sheets ledger is authoritative for later recovery.
            if self.journal.get(operation_id)["state"] == "sending":
                self.journal.transition(
                    operation_id,
                    "unknown",
                    "Yozilgan qiymatlarni tasdiqlash yakunlanmadi",
                )
            raise OutcomeUnknown(operation_id) from exc
        return result
