import pytest

from labpass.rules import DomainError, require_capacity, require_seat


@pytest.mark.parametrize("capacity,reserved", [(0, 0), (20, 20)])
def test_full_workshop(capacity, reserved):
    with pytest.raises(DomainError, match="workshop_full"):
        require_seat(capacity, reserved)


def test_available_and_capacity_boundary():
    require_seat(20, 19)
    require_capacity(20, 20)
    require_capacity(0, 0)
    with pytest.raises(DomainError, match="capacity_below_reservations"):
        require_capacity(19, 20)
