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


def _normalize_url(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    app_env: str = _env("APP_ENV", "development")
    log_level: str = _env("LOG_LEVEL", "INFO")

    chatwoot_base_url: str = _normalize_url(_env("CHATWOOT_BASE_URL"))
    chatwoot_account_id: int = _env_int("CHATWOOT_ACCOUNT_ID", 0)
    chatwoot_api_access_token: str = _env("CHATWOOT_API_ACCESS_TOKEN")
    chatwoot_webhook_secret: str = _env("CHATWOOT_WEBHOOK_SECRET")
    chatwoot_update_attributes: bool = _env_bool("CHATWOOT_UPDATE_ATTRIBUTES", True)
    chatwoot_sync_on_message_created: bool = _env_bool(
        "CHATWOOT_SYNC_ON_MESSAGE_CREATED", False
    )

    odoo_url: str = _normalize_url(_env("ODOO_URL", "https://engosoft.com"))
    odoo_db: str = _env("ODOO_DB")
    odoo_username: str = _env("ODOO_USERNAME")
    odoo_password: str = _env("ODOO_PASSWORD")

    allow_unsigned_webhooks: bool = _env_bool("ALLOW_UNSIGNED_WEBHOOKS", False)
    webhook_tolerance_seconds: int = _env_int("WEBHOOK_TOLERANCE_SECONDS", 300)
    sync_ttl_seconds: int = _env_int("SYNC_TTL_SECONDS", 1800)
    max_leads: int = _env_int("MAX_LEADS", 5)
    max_orders: int = _env_int("MAX_ORDERS", 5)
    app_state_db_path: Path = Path(_env("APP_STATE_DB_PATH", "data/integration.sqlite3"))

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
    return Settings()
