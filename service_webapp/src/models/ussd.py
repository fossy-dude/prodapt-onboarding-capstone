"""Pydantic models for the USSD callback endpoint (Story 4.4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

UssdMenuState = Literal[
    "root",
    "balance",
    "plan",
    "recharge_select",
    "recharge_confirm",
    "notifications",
]


class UssdCallbackRequest(BaseModel):
    """Inbound USSD callback payload from telecom operator (AC #1)."""

    model_config = ConfigDict(extra="forbid")

    msisdn: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    button_pressed: str = ""
    ussd_string: str = ""


__all__ = ["UssdCallbackRequest", "UssdMenuState"]
