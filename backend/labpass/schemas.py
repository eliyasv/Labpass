from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator

Capacity = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        try:
            result = validate_email(
                value, check_deliverability=False, allow_smtputf8=False, test_environment=True
            )
        except EmailNotValidError:
            raise ValueError("Invalid email address") from None
        # ASCII local parts and IDNA domains; product treats email as case-insensitive.
        normalized = result.ascii_email.lower()
        if len(normalized) > 254:
            raise ValueError("Email address is too long")
        return normalized


class Registration(Login):
    password: Annotated[SecretStr, Field(min_length=12, max_length=128)]


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    is_admin: bool


class AuthView(BaseModel):
    user: UserView
    csrf_token: str
    expires_at: datetime


class BookingCreate(Input):
    workshop_id: UUID


class CapacityUpdate(Input):
    capacity: Capacity


class WorkshopCreate(CapacityUpdate):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BookingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    workshop_id: UUID
    status: Literal["active", "cancelled"]
    created_at: datetime
    cancelled_at: datetime | None


class WorkshopView(BaseModel):
    id: UUID
    title: str
    capacity: int
    reserved: int
    available: int

    @classmethod
    def from_workshop(cls, workshop):
        return cls(
            id=workshop.id,
            title=workshop.title,
            capacity=workshop.capacity,
            reserved=workshop.reserved,
            available=workshop.capacity - workshop.reserved,
        )
