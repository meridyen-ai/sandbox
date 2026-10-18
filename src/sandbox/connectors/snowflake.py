"""
Snowflake Connector

Uses snowflake-connector-python. The account is the form's Account (a bare
identifier or the account URL); how the secret is used follows the form's
authentication type.
"""

from __future__ import annotations

import re
from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, InformationSchemaMixin

_ACCOUNT_URL = re.compile(r"^(?:https?://)?([^/]+?)(?:\.snowflakecomputing\.com)?(?:[:/].*)?$", re.I)


class SnowflakeConnector(InformationSchemaMixin, DBAPIConnector):
    """Snowflake."""

    label = "Snowflake"
    driver_modules = ("snowflake.connector",)
    placeholder = "%s"

    def _account(self) -> str:
        raw = str(self._require(self._param("account") or self.config.host, "account")).strip()
        match = _ACCOUNT_URL.match(raw)
        return match.group(1) if match else raw

    def _host(self) -> str:
        return f"{self._account()}.snowflakecomputing.com"

    def _open(self) -> Any:
        import snowflake.connector

        cfg = self.config
        secret = cfg.password.get_secret_value()
        params: dict[str, Any] = {
            "account": self._account(),
            "user": cfg.username or self._param("user"),
            "login_timeout": cfg.connection_timeout,
            "network_timeout": cfg.query_timeout,
            "application": "Meridyen",
        }
        for key, value in (
            ("warehouse", self._param("warehouse")),
            ("role", self._param("role")),
            ("database", cfg.database or None),
            ("schema", self._schema(None)),
        ):
            if value:
                params[key] = value

        auth_type = str(self._param("auth_type", "password"))
        if auth_type == "key_pair":
            params["private_key"] = _private_key_der(
                self._param("private_key") or secret,
                self._param("private_key_passphrase"),
            )
        elif auth_type in ("external_oauth", "external_oauth_pkce", "oauth_client_credentials"):
            params["authenticator"] = "oauth"
            params["token"] = self._param("oauth_token") or secret
        else:
            # A password, or a programmatic access token used as one.
            params["password"] = secret
        return snowflake.connector.connect(**params)

    def _default_schema(self) -> str | None:
        return "PUBLIC"

    def _catalog_prefix(self, schema: str | None) -> str:
        database = self.config.database
        return ('"' + database.replace('"', '""') + '".') if database else ""

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        sql, args = super()._entries_query(schema)
        return _any_case(sql), args

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        sql, args = super()._columns_query(schema, table)
        return _any_case(sql), args


def _any_case(sql: str) -> str:
    """Match the schema whatever case it was typed in: unquoted Snowflake
    names are stored upper-case."""
    return sql.replace("table_schema = %s", "UPPER(table_schema) = UPPER(%s)")


def _private_key_der(pem: Any, passphrase: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        str(pem).encode(),
        password=str(passphrase).encode() if passphrase else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
