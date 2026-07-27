"""Pydantic models for appointment scheduling draft pipeline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CustomerContactRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    customer: str = ""
    transit_time: str = ""


class PickupDropoffData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_data: dict[str, object] = Field(default_factory=dict)
    dropoff_data: dict[str, object] = Field(default_factory=dict)
    raw_rate: str = ""
    cleaned_rate: float = 0.0
    miles: float = 0.0
    po_number: str = ""
    pallet_count: int = 0
    weight_lbs: int = 0
    weight_units: str = ""
    pro_number: str = ""


class DraftStatic(BaseModel):
    """Internal intake shape for email draft building; not persisted in lifecycle metadata."""

    model_config = ConfigDict(extra="forbid")

    reference_number: str = ""
    shipment_details: str = ""
    name: str = ""
    description: str = ""
    email_name: str = ""
    email: str = ""
    domain_name: str = ""
    phone: str = ""
    commodity: str = ""


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str
    cc: list[str] = Field(default_factory=list)
    subject: str
    full_html: str


class AppointmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_number: str = ""
    shipment_details: str = ""
    proposed_pickup_at: str | None = None
    proposed_delivery_at: str | None = None


class LlmAppointmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculated_delivery_date: str = ""
    calculated_delivery_weekday: str = ""
    selected_pickup_date: str | None = None
    selected_pickup_time: str | None = None
    pcs_pickup_date: str | None = None
    transit_days: int | None = None
    weekend_shifted: bool = False
