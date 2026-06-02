from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class AgentContext:
    email: str | None = None
    agent_id: str | None = None
    name: str | None = None

    @property
    def normalized_email(self) -> str:
        return (self.email or "").strip().lower()

    @property
    def normalized_id(self) -> str:
        return str(self.agent_id or "").strip().lower()

    @property
    def email_domain(self) -> str:
        email = self.normalized_email
        if "@" not in email:
            return ""
        return email.rsplit("@", 1)[1]


def can_view_sensitive_data(agent: AgentContext, settings: Settings) -> bool:
    if not settings.restricted_dashboard_sections:
        return True

    if not any(
        [
            settings.sensitive_data_allowed_agent_emails,
            settings.sensitive_data_allowed_agent_ids,
            settings.sensitive_data_allowed_agent_domains,
        ]
    ):
        return False

    if agent.normalized_email in settings.sensitive_data_allowed_agent_emails:
        return True

    if agent.normalized_id in settings.sensitive_data_allowed_agent_ids:
        return True

    return agent.email_domain in settings.sensitive_data_allowed_agent_domains


def restricted_sections_for(agent: AgentContext, settings: Settings) -> list[str]:
    if can_view_sensitive_data(agent, settings):
        return []
    return sorted(settings.restricted_dashboard_sections)
