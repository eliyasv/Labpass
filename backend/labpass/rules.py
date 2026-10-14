class DomainError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)


def require_seat(capacity: int, reserved: int):
    if reserved >= capacity:
        raise DomainError(409, "workshop_full")


def require_capacity(capacity: int, reserved: int):
    if capacity < reserved:
        raise DomainError(409, "capacity_below_reservations")
