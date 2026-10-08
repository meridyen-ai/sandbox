"""SSL mode -> driver argument mapping, and the cases that must refuse to connect.

Every driver is replaced by a fake: nothing here opens a socket.
"""

from __future__ import annotations

import datetime
import ssl

import pytest
from pydantic import SecretStr

from sandbox.connectors import mssql as mssql_module
from sandbox.connectors import mysql as mysql_module
from sandbox.connectors import postgresql as postgresql_module
from sandbox.connectors import saphana as saphana_module
from sandbox.connectors import tls
from sandbox.connectors.mssql import MSSQLConnector, mssql_encryption
from sandbox.connectors.mysql import MySQLConnector, _TLSNotEstablished, _TLSRequiredConnection
from sandbox.connectors.postgresql import PostgreSQLConnector
from sandbox.connectors.saphana import hana_tls_params
from sandbox.core.config import DatabaseConnectionConfig, DatabaseType
from sandbox.core.exceptions import ConnectionError


def _self_signed_pem(common_name: str = "test-ca") -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture(scope="module")
def ca_pem() -> str:
    return _self_signed_pem()


def cfg(db_type: DatabaseType = DatabaseType.POSTGRESQL, **kw) -> DatabaseConnectionConfig:
    return DatabaseConnectionConfig(
        id="c1",
        name="c1",
        db_type=db_type,
        host="db.example.com",
        port=kw.pop("port", 5432),
        database="app",
        username="u",
        password=SecretStr("not-a-real-password"),
        **kw,
    )


# ---------------------------------------------------------------- tls.py


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("require", "require"),
        (" Verify-Full ", "verify-full"),
        ("verify_ca", "verify-ca"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_ssl_mode(raw, expected):
    assert tls.normalize_ssl_mode(raw) == expected


@pytest.mark.parametrize("raw", ["true", "on", "verify", "tls"])
def test_normalize_ssl_mode_rejects_anything_else(raw):
    with pytest.raises(ValueError):
        tls.normalize_ssl_mode(raw)


@pytest.mark.parametrize(
    "kw, expected",
    [
        ({}, "disable"),
        ({"ssl_enabled": False}, "disable"),
        ({"ssl_enabled": True}, "require"),
        ({"ssl_enabled": True, "ssl_ca_cert": "/etc/ssl/ca.pem"}, "verify-full"),
        # An explicit mode decides; the switch is ignored.
        ({"ssl_enabled": True, "ssl_mode": "disable"}, "disable"),
        ({"ssl_enabled": False, "ssl_mode": "verify-ca"}, "verify-ca"),
        ({"ssl_mode": "prefer"}, "prefer"),
    ],
)
def test_resolve_ssl_mode_keeps_the_old_switch_meaning(kw, expected):
    assert tls.resolve_ssl_mode(cfg(**kw)) == expected


def test_ca_certificate_accepts_pem_and_bundles(ca_pem):
    assert tls.validate_ca_certificate(f"\n  {ca_pem}  \n") == ca_pem.strip() + "\n"
    bundle = tls.validate_ca_certificate(ca_pem + _self_signed_pem("second"))
    assert bundle.count("BEGIN CERTIFICATE") == 2
    assert tls.validate_ca_certificate("   ") is None
    assert tls.validate_ca_certificate(None) is None


def test_ca_certificate_rejects_what_is_not_a_certificate(ca_pem):
    not_x509 = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"
    private_key = "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"
    for bad in ("hello", "/etc/ssl/certs/ca.pem", not_x509, ca_pem + private_key, ca_pem + "trailing"):
        with pytest.raises(ValueError):
            tls.validate_ca_certificate(bad)


def test_ca_certificate_size_is_bounded(ca_pem):
    copies = tls.MAX_CA_CERT_BYTES // len(ca_pem) + 1
    with pytest.raises(ValueError, match="too large"):
        tls.validate_ca_certificate(ca_pem * copies)


def test_context_disable_is_no_context():
    assert tls.build_ssl_context("disable", None) is None


@pytest.mark.parametrize("mode", ["allow", "prefer", "require"])
def test_context_non_verifying_modes_encrypt_without_verifying(mode, ca_pem):
    context = tls.build_ssl_context(mode, None)
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_context_verify_ca_checks_the_chain_not_the_name(ca_pem):
    context = tls.build_ssl_context("verify-ca", ca_pem)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is False
    # Only the given CA is trusted, not the system store.
    assert context.cert_store_stats()["x509_ca"] == 1


def test_context_verify_full_checks_chain_and_name(ca_pem):
    context = tls.build_ssl_context("verify-full", ca_pem)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] == 1


def test_context_without_ca_uses_the_system_store(monkeypatch):
    monkeypatch.setattr(tls, "_has_system_trust_store", lambda context: True)
    context = tls.build_ssl_context("verify-full", None)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
def test_context_refuses_when_nothing_can_verify(mode, monkeypatch):
    monkeypatch.setattr(tls, "_has_system_trust_store", lambda context: False)
    with pytest.raises(ConnectionError, match="Not connecting"):
        tls.build_ssl_context(mode, None)


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
@pytest.mark.parametrize("ca", ["/nonexistent/ca.pem", "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"])
def test_context_refuses_an_unloadable_ca(mode, ca):
    with pytest.raises(ConnectionError, match="Not connecting"):
        tls.build_ssl_context(mode, ca)


# ------------------------------------- what the contexts do in a handshake
#
# An in-memory TLS handshake (no socket) against a server whose certificate is
# issued by ``ca_pem`` for the name "db.example.com".


def _issued_server_context(tmp_path, issuer_name: str = "handshake-ca"):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "db.example.com")]))
        .issuer_name(ca_name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("db.example.com")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "server.pem", tmp_path / "server.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(str(cert_file), str(key_file))
    return server, ca_cert.public_bytes(serialization.Encoding.PEM).decode()


def _handshake(client_context: ssl.SSLContext, server_context: ssl.SSLContext, host: str) -> None:
    to_server, to_client = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_context.wrap_bio(to_client, to_server, server_hostname=host)
    server = server_context.wrap_bio(to_server, to_client, server_side=True)
    for _ in range(20):
        done = 0
        for side in (client, server):
            try:
                side.do_handshake()
                done += 1
            except ssl.SSLWantReadError:
                pass
        if done == 2:
            return
    raise AssertionError("handshake did not finish")


def test_handshake_verify_full_accepts_the_right_ca_and_name(tmp_path):
    server, issuing_ca = _issued_server_context(tmp_path)
    _handshake(tls.build_ssl_context("verify-full", issuing_ca), server, "db.example.com")


def test_handshake_verify_full_rejects_another_host_name(tmp_path):
    server, issuing_ca = _issued_server_context(tmp_path)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(tls.build_ssl_context("verify-full", issuing_ca), server, "impostor.example.com")


def test_handshake_verify_ca_ignores_the_name_but_not_the_chain(tmp_path, ca_pem):
    server, issuing_ca = _issued_server_context(tmp_path)
    _handshake(tls.build_ssl_context("verify-ca", issuing_ca), server, "impostor.example.com")
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(tls.build_ssl_context("verify-ca", ca_pem), server, "db.example.com")


def test_handshake_given_ca_replaces_the_system_store(tmp_path, ca_pem):
    server, _issuing_ca = _issued_server_context(tmp_path)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(tls.build_ssl_context("verify-full", ca_pem), server, "db.example.com")


def test_handshake_require_accepts_any_certificate(tmp_path):
    server, _issuing_ca = _issued_server_context(tmp_path)
    _handshake(tls.build_ssl_context("require", None), server, "impostor.example.com")


# ------------------------------------------------------------ PostgreSQL


class _FakePgConnection:
    _transport = None

    async def execute(self, *_a, **_k):
        return None


@pytest.fixture
def pg_connect(monkeypatch):
    calls: list[dict] = []

    async def fake_connect(**kwargs):
        calls.append(kwargs)
        return _FakePgConnection()

    monkeypatch.setattr(postgresql_module.asyncpg, "connect", fake_connect)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw, expected",
    [
        ({}, False),
        ({"ssl_enabled": False}, False),
        ({"ssl_mode": "disable", "ssl_enabled": True}, False),
        ({"ssl_mode": "allow"}, "allow"),
        ({"ssl_mode": "prefer"}, "prefer"),
    ],
)
async def test_postgres_modes_without_a_context(pg_connect, kw, expected):
    await PostgreSQLConnector(cfg(**kw)).connect()
    assert pg_connect[0]["ssl"] is expected or pg_connect[0]["ssl"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"ssl_mode": "require"}, {"ssl_enabled": True}])
async def test_postgres_require_encrypts_without_verifying(pg_connect, kw):
    await PostgreSQLConnector(cfg(**kw)).connect()
    context = pg_connect[0]["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, checks_name", [("verify-ca", False), ("verify-full", True)])
async def test_postgres_verifying_modes(pg_connect, ca_pem, mode, checks_name):
    await PostgreSQLConnector(cfg(ssl_mode=mode, ssl_ca_cert=ca_pem)).connect()
    context = pg_connect[0]["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is checks_name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw",
    [
        {"ssl_mode": "verify-full", "ssl_ca_cert": "/nonexistent/ca.pem"},
        {"ssl_mode": "verify-ca", "ssl_ca_cert": "/nonexistent/ca.pem"},
        # The old switch with a CA path that is gone: still verifying, still refused.
        {"ssl_enabled": True, "ssl_ca_cert": "/nonexistent/ca.pem"},
    ],
)
async def test_postgres_never_connects_when_it_cannot_verify(pg_connect, kw):
    with pytest.raises(ConnectionError, match="Not connecting"):
        await PostgreSQLConnector(cfg(**kw)).connect()
    assert pg_connect == []


# ----------------------------------------------------------------- MySQL


class _FakeMySQLConnection:
    instances: list["_FakeMySQLConnection"] = []
    secure = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._secure = type(self).secure
        self.closed = False
        type(self).instances.append(self)

    async def _connect(self):
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def mysql_drivers(monkeypatch):
    plain_calls: list[dict] = []

    async def fake_connect(**kwargs):
        plain_calls.append(kwargs)
        return object()

    _FakeMySQLConnection.instances = []
    _FakeMySQLConnection.secure = True
    monkeypatch.setattr(mysql_module.aiomysql, "connect", fake_connect)
    monkeypatch.setattr(mysql_module, "_TLSRequiredConnection", _FakeMySQLConnection)
    return plain_calls, _FakeMySQLConnection


def mysql_cfg(**kw) -> DatabaseConnectionConfig:
    return cfg(DatabaseType.MYSQL, port=3306, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{}, {"ssl_mode": "disable", "ssl_enabled": True}])
async def test_mysql_disable_sends_no_context(mysql_drivers, kw):
    plain_calls, strict = mysql_drivers
    await MySQLConnector(mysql_cfg(**kw)).connect()
    assert plain_calls[0]["ssl"] is None
    assert strict.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["allow", "prefer"])
async def test_mysql_prefer_offers_tls_and_accepts_plaintext(mysql_drivers, mode):
    plain_calls, strict = mysql_drivers
    await MySQLConnector(mysql_cfg(ssl_mode=mode)).connect()
    assert plain_calls[0]["ssl"].verify_mode == ssl.CERT_NONE
    assert strict.instances == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{"ssl_mode": "require"}, {"ssl_enabled": True}])
async def test_mysql_require_uses_the_strict_connection(mysql_drivers, kw):
    plain_calls, strict = mysql_drivers
    await MySQLConnector(mysql_cfg(**kw)).connect()
    assert plain_calls == []
    context = strict.instances[0].kwargs["ssl"]
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, checks_name", [("verify-ca", False), ("verify-full", True)])
async def test_mysql_verifying_modes(mysql_drivers, ca_pem, mode, checks_name):
    _plain, strict = mysql_drivers
    await MySQLConnector(mysql_cfg(ssl_mode=mode, ssl_ca_cert=ca_pem)).connect()
    context = strict.instances[0].kwargs["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is checks_name


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
async def test_mysql_refuses_a_session_that_is_not_encrypted(mysql_drivers, ca_pem, mode):
    _plain, strict = mysql_drivers
    strict.secure = False
    ca = ca_pem if mode != "require" else None
    with pytest.raises(ConnectionError, match="does not offer TLS"):
        await MySQLConnector(mysql_cfg(ssl_mode=mode, ssl_ca_cert=ca)).connect()
    assert strict.instances[0].closed is True


@pytest.mark.asyncio
async def test_mysql_never_connects_when_it_cannot_verify(mysql_drivers):
    plain_calls, strict = mysql_drivers
    with pytest.raises(ConnectionError, match="Not connecting"):
        await MySQLConnector(mysql_cfg(ssl_mode="verify-full", ssl_ca_cert="/nonexistent/ca.pem")).connect()
    assert plain_calls == [] and strict.instances == []


@pytest.mark.asyncio
async def test_mysql_strict_connection_stops_before_signing_in(monkeypatch):
    signed_in: list[bool] = []

    async def fake_authentication(self):
        signed_in.append(True)

    monkeypatch.setattr(mysql_module.Connection, "_request_authentication", fake_authentication)
    conn = object.__new__(_TLSRequiredConnection)
    conn._writer = None  # what Connection.__del__ looks at

    conn.server_capabilities = 0
    with pytest.raises(_TLSNotEstablished):
        await conn._request_authentication()
    assert signed_in == []

    conn.server_capabilities = mysql_module.CLIENT.SSL
    await conn._request_authentication()
    assert signed_in == [True]


# ------------------------------------------------------------ SQL Server


@pytest.mark.parametrize(
    "mode, expected",
    [
        (None, None),
        ("", None),
        ("disable", "off"),
        ("allow", "request"),
        ("prefer", "request"),
        ("require", "require"),
    ],
)
def test_mssql_encryption_setting(mode, expected):
    assert mssql_encryption(mode) == expected


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
def test_mssql_refuses_modes_it_cannot_verify(mode):
    with pytest.raises(ConnectionError, match="cannot verify"):
        mssql_encryption(mode)


class _FakeMSSQLConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def mssql_driver(monkeypatch):
    state = {"calls": [], "negotiated": "7.4", "conn": _FakeMSSQLConnection()}

    def fake_connect_mssql(tds_version=None, **kwargs):
        state["calls"].append(kwargs)
        return state["conn"], state["negotiated"]

    monkeypatch.setattr(mssql_module, "connect_mssql", fake_connect_mssql)
    monkeypatch.setattr(mssql_module, "detect_codepage", lambda conn: 1252)
    return state


def mssql_cfg(**kw) -> DatabaseConnectionConfig:
    return cfg(DatabaseType.MSSQL, port=1433, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("kw", [{}, {"ssl_enabled": True}, {"ssl_enabled": False}])
async def test_mssql_saved_connections_keep_the_driver_default(mssql_driver, kw):
    connector = MSSQLConnector(mssql_cfg(**kw))
    await connector.close_connection(await connector.connect())
    assert "encryption" not in mssql_driver["calls"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode, expected", [("disable", "off"), ("prefer", "request"), ("require", "require")])
async def test_mssql_explicit_modes_reach_the_driver(mssql_driver, mode, expected):
    connector = MSSQLConnector(mssql_cfg(ssl_mode=mode))
    await connector.close_connection(await connector.connect())
    assert mssql_driver["calls"][0]["encryption"] == expected


@pytest.mark.asyncio
async def test_mssql_verifying_mode_never_reaches_the_driver(mssql_driver):
    with pytest.raises(ConnectionError, match="cannot verify"):
        await MSSQLConnector(mssql_cfg(ssl_mode="verify-full")).connect()
    assert mssql_driver["calls"] == []


@pytest.mark.asyncio
async def test_mssql_require_refuses_a_protocol_that_cannot_encrypt(mssql_driver):
    mssql_driver["negotiated"] = "7.0"
    with pytest.raises(ConnectionError, match="cannot encrypt"):
        await MSSQLConnector(mssql_cfg(ssl_mode="require")).connect()
    assert mssql_driver["conn"].closed is True


# -------------------------------------------------------------- SAP HANA


def test_hana_disable_and_require():
    assert hana_tls_params("disable", None) == {}
    assert hana_tls_params("require", None) == {"encrypt": True, "sslValidateCertificate": False}


def test_hana_verifying_modes(ca_pem):
    full = hana_tls_params("verify-full", ca_pem)
    assert full["encrypt"] is True
    assert full["sslValidateCertificate"] is True
    assert full["sslTrustStore"] == ca_pem
    assert "sslHostNameInCertificate" not in full

    chain_only = hana_tls_params("verify-ca", ca_pem)
    assert chain_only["sslValidateCertificate"] is True
    assert chain_only["sslHostNameInCertificate"] == "*"


def test_hana_without_ca_uses_the_system_store(monkeypatch):
    monkeypatch.setattr(saphana_module, "system_ca_file", lambda: "/etc/ssl/certs/ca-certificates.crt")
    params = hana_tls_params("verify-full", None)
    assert params["sslTrustStore"] == "/etc/ssl/certs/ca-certificates.crt"
    assert params["sslValidateCertificate"] is True


@pytest.mark.parametrize("mode", ["verify-ca", "verify-full"])
def test_hana_refuses_when_nothing_can_verify(mode, monkeypatch):
    monkeypatch.setattr(saphana_module, "system_ca_file", lambda: None)
    with pytest.raises(ConnectionError, match="Not connecting"):
        hana_tls_params(mode, None)


@pytest.mark.parametrize("mode", ["allow", "prefer"])
def test_hana_refuses_modes_the_driver_does_not_have(mode):
    with pytest.raises(ConnectionError, match="not available"):
        hana_tls_params(mode, None)
