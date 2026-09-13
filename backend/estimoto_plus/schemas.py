from __future__ import annotations

from datetime import date as Date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileWrite(Strict):
    name: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=50)
    postal_code: str = Field(default="", max_length=30)
    contact_preference: Literal["email", "phone"] = "email"


class VehicleCreate(Strict):
    year: int = Field(ge=1886, le=2100)
    make: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    nickname: str = Field(default="", max_length=100)
    vin: str = Field(default="", max_length=40)
    mileage: int = Field(default=0, ge=0)
    insurer: str = Field(default="", max_length=100)
    policy_number: str = Field(default="", max_length=100)


class VehicleUpdate(Strict):
    year: int | None = Field(default=None, ge=1886, le=2100)
    make: str | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = Field(default=None, min_length=1, max_length=100)
    nickname: str | None = Field(default=None, max_length=100)
    vin: str | None = Field(default=None, max_length=40)
    mileage: int | None = Field(default=None, ge=0)
    insurer: str | None = Field(default=None, max_length=100)
    policy_number: str | None = Field(default=None, max_length=100)


class EstimateCreate(Strict):
    vehicle_id: str
    discipline: Literal["pdr", "collision"]
    description: str = Field(min_length=1, max_length=5000)
    claim_number: str = Field(default="", max_length=100)
    date_of_loss: Date | None = None


class ReminderCreate(Strict):
    vehicle_id: str
    title: str = Field(min_length=1, max_length=200)
    due_date: Date | None = None
    due_mileage: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def due_required(self):
        if self.due_date is None and self.due_mileage is None:
            raise ValueError("A date or mileage is required")
        return self


class RequestCreate(Strict):
    vehicle_id: str
    provider_id: str
    specialty: Literal["pdr", "collision", "maintenance", "mechanical"]
    description: str = Field(min_length=1, max_length=5000)
    preferred_time: str = Field(default="", max_length=200)
    share_contact: Literal[True]


class AssistantInput(Strict):
    message: str = Field(min_length=1, max_length=2000)
    vehicle_id: str | None = None
    postal_code: str | None = Field(default=None, max_length=30)
    specialty: Literal["pdr", "collision", "maintenance", "mechanical"] | None = None
    mobile_only: bool = False


class ProviderPublish(Strict):
    source_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["shop", "technician"]
    specialties: list[Literal["pdr", "collision", "maintenance", "mechanical"]]
    postal_codes: list[str]
    city: str = ""
    address: str = ""
    phone: str = ""
    mobile_service: bool = False
    accepting_requests: bool = False
    public_visible: bool = False
    description: str = ""


class RequestInboundEvent(Strict):
    event_id: str = Field(min_length=1, max_length=100)
    provider_id: str
    status: Literal["accepted", "scheduled", "declined", "cancelled", "completed"]
    message: str = Field(default="", max_length=2000)
    scheduled_at: datetime | None = None


class EstimateSnapshot(Strict):
    source_id: str
    customer_id: str
    vehicle_id: str
    discipline: Literal["pdr", "collision"]
    description: str
    claim_number: str = ""
    date_of_loss: Date | None = None
    status: Literal["submitted", "reviewing", "ready", "approved"]
    amount_cents: int | None = Field(default=None, ge=0)
    provider_name: str = ""


class RepairStage(Strict):
    title: str
    status: Literal["completed", "current", "upcoming"]
    date: Date | None = None


class RepairSnapshot(Strict):
    source_id: str
    customer_id: str
    vehicle_id: str
    provider_name: str
    title: str
    status: str
    estimated_completion: Date | None = None
    stages: list[RepairStage]
