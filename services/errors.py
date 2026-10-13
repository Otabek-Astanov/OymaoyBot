"""Safe, explicit errors shared by storage and Telegram handlers."""


class ServiceError(Exception):
    """Expected operational failure that may be shown without credentials."""


class StorageUnavailable(ServiceError):
    pass


class StorageReadError(ServiceError):
    pass


class StorageWriteError(ServiceError):
    pass


class SchemaError(StorageReadError):
    pass


class BusinessRuleError(ServiceError):
    pass


class AccessDenied(BusinessRuleError):
    pass


class OutcomeUnknown(ServiceError):
    def __init__(self, operation_id: str):
        self.operation_id = operation_id
        super().__init__(f"Amal natijasi aniqlanmadi. Amal ID: {operation_id}")


class AmbiguousPhone(BusinessRuleError):
    def __init__(self, matches: list[dict]):
        self.matches = matches
        super().__init__(
            "Bir nechta telefon topildi. To'liq IMEI yoki Telefon ID ni tanlang."
        )
