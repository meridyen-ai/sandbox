"""
Trino, Starburst and Presto Connectors

All three are coordinators reached over HTTP that expose every catalog's
``information_schema``. Trino and Starburst use the trino client; Presto, whose
protocol headers differ, uses PyHive's.

The form's Catalog is the connection's database.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, InformationSchemaMixin


class _CoordinatorConnector(InformationSchemaMixin, DBAPIConnector):
    """What the Trino family shares: a catalog, a schema and an HTTP scheme."""

    def _catalog(self) -> str:
        return self._require(self._param("catalog") or self.config.database, "catalog")

    def _catalog_prefix(self, schema: str | None) -> str:
        return '"' + self._catalog().replace('"', '""') + '".'

    def _default_schema(self) -> str | None:
        return "default"

    def _scheme(self) -> tuple[str, bool | str]:
        """``(scheme, verify)``. A stated SSL mode decides; otherwise the
        form's HTTP scheme does, or the port."""
        cfg = self.config
        if cfg.ssl_mode or cfg.ssl_enabled:
            return self._http_tls()
        scheme = str(self._param("http_scheme", "")).strip().lower()
        if scheme not in ("http", "https"):
            scheme = "https" if cfg.port in (443, 8443) else "http"
        if scheme == "https":
            return scheme, self._ca_file() or True
        return scheme, False


class TrinoConnector(_CoordinatorConnector):
    """Trino."""

    label = "Trino"
    driver_modules = ("trino",)

    def _open(self) -> Any:
        import trino

        cfg = self.config
        scheme, verify = self._scheme()
        password = cfg.password.get_secret_value()
        conn = trino.dbapi.connect(
            host=cfg.host,
            port=cfg.port or (443 if scheme == "https" else 8080),
            user=cfg.username,
            catalog=self._catalog(),
            schema=self._schema(None),
            http_scheme=scheme,
            auth=trino.auth.BasicAuthentication(cfg.username, password) if password else None,
            verify=verify,
            request_timeout=float(cfg.connection_timeout),
        )
        # The client dials on first use; do it now so a bad address fails here.
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        return conn


class StarburstConnector(TrinoConnector):
    """Starburst Enterprise and Starburst Galaxy (Trino underneath)."""

    label = "Starburst"


class PrestoConnector(_CoordinatorConnector):
    """Presto (PrestoDB)."""

    label = "Presto"
    driver_modules = ("pyhive",)
    placeholder = "%s"

    def _open(self) -> Any:
        from pyhive import presto

        cfg = self.config
        scheme, verify = self._scheme()
        password = cfg.password.get_secret_value()
        conn = presto.connect(
            host=cfg.host,
            port=cfg.port or (443 if scheme == "https" else 8080),
            username=cfg.username,
            password=password or None,
            catalog=self._catalog(),
            schema=self._schema(None),
            protocol=scheme,
            requests_kwargs={"verify": verify} if scheme == "https" else None,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        return conn
