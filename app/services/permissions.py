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
    """All dashboard sections are intentionally visible to every Chatwoot agent."""
    return True


def restricted_sections_for(agent: AgentContext, settings: Settings) -> list[str]:
    """Keep the legacy response field while exposing every dashboard section."""
    return []
