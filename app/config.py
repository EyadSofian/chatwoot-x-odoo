from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if not value:
        return default
    return int(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_set(name: str, default: str = "") -> frozenset[str]:
    value = _env(name, default)
    if not value:
        return frozenset()
    return frozenset(item.strip().lower() for item in value.split(",") if item.strip())


def _normalize_url(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str

    chatwoot_base_url: str
    chatwoot_account_id: int
    chatwoot_api_access_token: str
    chatwoot_webhook_secret: str
    chatwoot_auto_private_notes: bool
    chatwoot_update_attributes: bool
    chatwoot_update_sensitive_attributes: bool
    chatwoot_sync_on_message_created: bool
    dashboard_app_token: str
    sensitive_data_allowed_agent_emails: frozenset[str]
    sensitive_data_allowed_agent_ids: frozenset[str]
    sensitive_data_allowed_agent_domains: frozenset[str]
    restricted_dashboard_sections: frozenset[str]

    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_password: str

    allow_unsigned_webhooks: bool
    webhook_tolerance_seconds: int
    sync_ttl_seconds: int
    max_leads: int
    max_orders: int
    max_invoices: int
    max_journal_entries: int
    max_courses: int
    app_state_db_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=_env("APP_ENV", "development"),
            log_level=_env("LOG_LEVEL", "INFO"),
            chatwoot_base_url=_normalize_url(_env("CHATWOOT_BASE_URL")),
            chatwoot_account_id=_env_int("CHATWOOT_ACCOUNT_ID", 0),
            chatwoot_api_access_token=_env("CHATWOOT_API_ACCESS_TOKEN"),
            chatwoot_webhook_secret=_env("CHATWOOT_WEBHOOK_SECRET"),
            chatwoot_auto_private_notes=_env_bool("CHATWOOT_AUTO_PRIVATE_NOTES", False),
            chatwoot_update_attributes=_env_bool("CHATWOOT_UPDATE_ATTRIBUTES", True),
            chatwoot_update_sensitive_attributes=_env_bool(
                "CHATWOOT_UPDATE_SENSITIVE_ATTRIBUTES", False
            ),
            chatwoot_sync_on_message_created=_env_bool(
                "CHATWOOT_SYNC_ON_MESSAGE_CREATED", False
            ),
            dashboard_app_token=_env("DASHBOARD_APP_TOKEN"),
            sensitive_data_allowed_agent_emails=_env_set(
                "SENSITIVE_DATA_ALLOWED_AGENT_EMAILS"
            ),
            sensitive_data_allowed_agent_ids=_env_set("SENSITIVE_DATA_ALLOWED_AGENT_IDS"),
            sensitive_data_allowed_agent_domains=_env_set(
                "SENSITIVE_DATA_ALLOWED_AGENT_DOMAINS"
            ),
            restricted_dashboard_sections=_env_set(
                "RESTRICTED_DASHBOARD_SECTIONS", "orders,invoices"
            ),
            odoo_url=_normalize_url(_env("ODOO_URL", "https://engosoft.com")),
            odoo_db=_env("ODOO_DB"),
            odoo_username=_env("ODOO_USERNAME"),
            odoo_password=_env("ODOO_PASSWORD"),
            allow_unsigned_webhooks=_env_bool("ALLOW_UNSIGNED_WEBHOOKS", False),
            webhook_tolerance_seconds=_env_int("WEBHOOK_TOLERANCE_SECONDS", 300),
            sync_ttl_seconds=_env_int("SYNC_TTL_SECONDS", 1800),
            max_leads=_env_int("MAX_LEADS", 5),
            max_orders=_env_int("MAX_ORDERS", 5),
            max_invoices=_env_int("MAX_INVOICES", 5),
            max_journal_entries=_env_int("MAX_JOURNAL_ENTRIES", 5),
            max_courses=_env_int("MAX_COURSES", 5),
            app_state_db_path=Path(_env("APP_STATE_DB_PATH", "data/integration.sqlite3")),
        )

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        required = {
            "CHATWOOT_BASE_URL": self.chatwoot_base_url,
            "CHATWOOT_ACCOUNT_ID": self.chatwoot_account_id,
            "CHATWOOT_API_ACCESS_TOKEN": self.chatwoot_api_access_token,
            "ODOO_URL": self.odoo_url,
            "ODOO_DB": self.odoo_db,
            "ODOO_USERNAME": self.odoo_username,
            "ODOO_PASSWORD": self.odoo_password,
        }
        for name, value in required.items():
            if not value:
                missing.append(name)

        if not self.allow_unsigned_webhooks and not self.chatwoot_webhook_secret:
            missing.append("CHATWOOT_WEBHOOK_SECRET")

        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
