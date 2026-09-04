"""Plaintext Basic Auth settings for the local Picframe web UI."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from picframe.core.services.resource_paths import ResourcePaths

logger = logging.getLogger(__name__)

AuthScope = Literal["none", "settings", "site"]
AUTH_SCOPE_VALUES = {"none", "settings", "site"}
AUTH_COOKIE_NAME = "picframe_auth"


@dataclass(frozen=True)
class BasicAuthSettings:
    """Basic Auth settings persisted outside the main config database."""

    username: str = "admin"
    password: str = ""
    scope: AuthScope = "none"

    @property
    def enabled(self) -> bool:
        return self.scope != "none"

    @property
    def password_set(self) -> bool:
        return bool(self.password)


class BasicAuthStore:
    """Read, write, and verify plaintext Basic Auth settings."""

    def __init__(self, resource_paths: ResourcePaths) -> None:
        self._path = resource_paths.data_dir / "basic_auth.json"

    @property
    def path(self) -> Path:
        return self._path

    @staticmethod
    def _scope_from_saved_data(data: dict[str, Any]) -> AuthScope:
        raw_scope = str(data.get("scope") or "").strip().lower()
        if "enabled" in data and not bool(data.get("enabled")):
            return "none"
        if raw_scope in AUTH_SCOPE_VALUES:
            return cast(AuthScope, raw_scope)
        return "settings" if bool(data.get("enabled", False)) else "none"

    @staticmethod
    def _scope_from_update(scope: str | None, enabled: bool | None) -> AuthScope:
        raw_scope = str(scope or "").strip().lower()
        if raw_scope in AUTH_SCOPE_VALUES:
            return cast(AuthScope, raw_scope)
        if enabled is not None:
            return "settings" if enabled else "none"
        raise ValueError("Unsupported Basic Auth scope")

    def load(self) -> BasicAuthSettings:
        if not self._path.exists():
            return BasicAuthSettings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to read Basic Auth settings: %s", exc)
            return BasicAuthSettings()
        if not isinstance(data, dict):
            return BasicAuthSettings()
        return BasicAuthSettings(
            username=str(data.get("username") or "admin"),
            password=str(data.get("password") or ""),
            scope=self._scope_from_saved_data(data),
        )

    def public_config(self, *, include_password: bool = False) -> dict[str, Any]:
        settings = self.load()
        config = {
            "enabled": settings.enabled,
            "username": settings.username,
            "scope": settings.scope,
            "password_set": settings.password_set,
        }
        if include_password and settings.enabled:
            config["password"] = settings.password
        return config

    def update(
        self,
        *,
        scope: str | None = None,
        enabled: bool | None = None,
        username: str,
        password: str | None = None,
    ) -> BasicAuthSettings:
        current = self.load()
        next_scope = self._scope_from_update(scope, enabled)
        next_password = current.password if password is None or password == "" else password
        next_username = username.strip() or "admin"
        if next_scope != "none" and not next_password:
            raise ValueError("Password is required when Basic Auth is enabled")
        settings = BasicAuthSettings(
            username=next_username,
            password=next_password,
            scope=next_scope,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "enabled": settings.enabled,
                    "username": settings.username,
                    "password": settings.password,
                    "scope": settings.scope,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return settings

    def verify_authorization_header(self, header: str | None) -> bool:
        settings = self.load()
        if not settings.enabled:
            return True
        return self._verify_authorization_header(settings, header)

    def session_token(self) -> str:
        settings = self.load()
        if not settings.enabled or not settings.password:
            return ""
        return hashlib.sha256(
            f"{settings.scope}\0{settings.username}\0{settings.password}".encode()
        ).hexdigest()

    def verify_request_credentials(
        self,
        header: str | None,
        session_token: str | None = None,
    ) -> bool:
        settings = self.load()
        if not settings.enabled:
            return True
        if self._verify_authorization_header(settings, header):
            return True
        expected_token = self.session_token()
        if not session_token or not expected_token:
            return False
        return secrets.compare_digest(session_token, expected_token)

    def _verify_authorization_header(
        self,
        settings: BasicAuthSettings,
        header: str | None,
    ) -> bool:
        if not header:
            return False
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "basic" or not token:
            return False
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        username, sep, password = decoded.partition(":")
        if not sep:
            return False
        return secrets.compare_digest(username, settings.username) and secrets.compare_digest(
            password,
            settings.password,
        )
