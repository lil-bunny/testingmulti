"""Typed ``workflow_error_alerts`` blocks in ``tenants.settings``."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.tenant_settings.email_recipients import coerce_email_list

RequiredEmailList = list[str]
OptionalEmailList = list[str]


class WorkflowErrorAlertEmailChannelSettings(BaseModel):
    """Email channel: recipients, subject, and HTML body template."""

    model_config = ConfigDict(extra="ignore")

    channel: Literal["email"] = "email"
    to: RequiredEmailList = Field(min_length=1)
    cc: OptionalEmailList = Field(default_factory=list)
    bcc: OptionalEmailList = Field(default_factory=list)
    subject: str
    body_template: str

    @field_validator("to", mode="before")
    @classmethod
    def _to(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=True)

    @field_validator("cc", "bcc", mode="before")
    @classmethod
    def _cc_bcc(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=False)


class WorkflowErrorAlertSlackChannelSettings(BaseModel):
    """Slack channel placeholder until webhook delivery is implemented."""

    model_config = ConfigDict(extra="ignore")

    channel: Literal["slack"] = "slack"
    webhook_url: str = ""
    body_template: str | None = None


class WorkflowErrorAlertTeamsChannelSettings(BaseModel):
    """Teams channel placeholder until webhook delivery is implemented."""

    model_config = ConfigDict(extra="ignore")

    channel: Literal["teams"] = "teams"
    webhook_url: str = ""
    body_template: str | None = None


WorkflowErrorAlertChannelSettings = Annotated[
    WorkflowErrorAlertEmailChannelSettings
    | WorkflowErrorAlertSlackChannelSettings
    | WorkflowErrorAlertTeamsChannelSettings,
    Field(discriminator="channel"),
]


class WorkflowErrorAlertSettings(BaseModel):
    """Root or per-workflow alert routing: enabled flag and channel list."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    channels: list[WorkflowErrorAlertChannelSettings] = Field(default_factory=list)
