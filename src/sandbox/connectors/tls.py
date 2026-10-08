"""
TLS settings for database connections.

One connection carries an ``ssl_mode`` named after PostgreSQL's ``sslmode`` and
an optional CA certificate. What each mode promises, for every engine:

- ``disable``      no TLS.
- ``allow`` / ``prefer``  TLS when the server offers it, never verified.
- ``require``      TLS or no connection; the server certificate is NOT verified.
- ``verify-ca``    TLS, and the certificate chain must lead to the given CA
                   (or to the system trust store when no CA is given).
- ``verify-full``  ``verify-ca`` plus: the certificate must name the host.

A mode that verifies either verifies or refuses to connect. Nothing in here
falls back to a weaker mode.

Connections saved before ``ssl_mode`` existed only have the ``ssl_enabled``
switch; :func:`resolve_ssl_mode` maps it to the mode they have always had.
"""

from __future__ import annotations

import os
import re
import ssl
from typing import Any

from sandbox.core.exceptions import ConnectionError

SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
VERIFYING_SSL_MODES = ("verify-ca", "verify-full")

# A CA bundle is a handful of certificates; anything larger is not one.
MAX_CA_CERT_BYTES = 64 * 1024

_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+?-----END CERTIFICATE-----"
)


def normalize_ssl_mode(value: Any) -> str | None:
    """The canonical mode name, or None when no mode was given.

    Raises ValueError for anything that is not a mode.
    """
    if value is None:
        return None
    mode = str(value).strip().lower().replace("_", "-")
    if not mode:
        return None
    if mode not in SSL_MODES:
        raise ValueError(f"SSL mode must be one of: {', '.join(SSL_MODES)}")
    return mode


def is_pem(value: str | None) -> bool:
    """True when the value is certificate text rather than a path to a file."""
    return bool(value) and "-----BEGIN" in value


def validate_ca_certificate(value: Any) -> str | None:
    """A pasted CA certificate (PEM, one or more), normalized; None when empty.

    Raises ValueError when it is too large, carries anything other than
    certificates, or does not parse as X.509.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("CA certificate must be PEM text")
    text = value.strip()
    if not text:
        return None
    if len(text.encode("utf-8", errors="replace")) > MAX_CA_CERT_BYTES:
        raise ValueError(
            f"CA certificate is too large (limit {MAX_CA_CERT_BYTES // 1024} KB)"
        )
    if "PRIVATE KEY" in text:
        raise ValueError(
            "CA certificate must contain certificates only, never a private key"
        )
    blocks = _PEM_CERT_RE.findall(text)
    if not blocks or _PEM_CERT_RE.sub("", text).strip():
        raise ValueError(
            "CA certificate must be PEM text: one or more blocks from "
            "-----BEGIN CERTIFICATE----- to -----END CERTIFICATE-----"
        )
    pem = "\n".join(block.strip() for block in blocks) + "\n"
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=pem)
    except (ssl.SSLError, ValueError) as e:
        raise ValueError("CA certificate is not a valid X.509 certificate") from e
    return pem


def resolve_ssl_mode(cfg: Any) -> str:
    """The mode a connection runs with.

    An explicit ``ssl_mode`` wins. Without one the old switch decides, with the
    behaviour it has always had: off = no TLS; on = TLS without verification,
    or full verification when a CA certificate was configured.
    """
    mode = normalize_ssl_mode(getattr(cfg, "ssl_mode", None))
    if mode:
        return mode
    if not getattr(cfg, "ssl_enabled", False):
        return "disable"
    return "verify-full" if getattr(cfg, "ssl_ca_cert", None) else "require"


def _refuse(message: str, *, connection_id: str | None, db_type: str | None) -> ConnectionError:
    return ConnectionError(message, connection_id=connection_id, db_type=db_type)


def system_ca_file() -> str | None:
    """The system trust store as one PEM file, when the host has one."""
    paths = ssl.get_default_verify_paths()
    for candidate in (paths.cafile, paths.openssl_cafile):
        if candidate and os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


def _has_system_trust_store(context: ssl.SSLContext) -> bool:
    if context.cert_store_stats().get("x509_ca", 0) > 0:
        return True
    # A hashed certificate directory is read on demand, so it is not counted.
    capath = ssl.get_default_verify_paths().capath
    try:
        return bool(capath) and os.path.isdir(capath) and any(os.scandir(capath))
    except OSError:
        return False


def build_ssl_context(
    mode: str,
    ca_cert: str | None,
    *,
    connection_id: str | None = None,
    db_type: str | None = None,
) -> ssl.SSLContext | None:
    """The TLS context for a mode, or None when the mode never needs one.

    ``allow``/``prefer``/``require`` get a context that encrypts and verifies
    nothing. The verifying modes get one that trusts only the given CA, or the
    system trust store when none is given, and raise when neither can be
    loaded: a connection that asked for verification never runs without it.
    """
    if mode == "disable":
        return None

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if mode not in VERIFYING_SSL_MODES:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    # PROTOCOL_TLS_CLIENT starts with CERT_REQUIRED and host name checking on.
    try:
        if ca_cert and is_pem(ca_cert):
            context.load_verify_locations(cadata=ca_cert)
        elif ca_cert:
            context.load_verify_locations(cafile=ca_cert)
        else:
            context.load_default_certs()
    except (ssl.SSLError, OSError, ValueError) as e:
        raise _refuse(
            f"SSL mode '{mode}' needs to verify the server certificate, but the CA "
            f"certificate could not be loaded ({e.__class__.__name__}). Not connecting.",
            connection_id=connection_id,
            db_type=db_type,
        ) from e
    if not ca_cert and not _has_system_trust_store(context):
        raise _refuse(
            f"SSL mode '{mode}' needs to verify the server certificate, but no CA "
            "certificate was given and this sandbox has no system trust store. "
            "Add the CA certificate to the connection. Not connecting.",
            connection_id=connection_id,
            db_type=db_type,
        )
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = mode == "verify-full"
    return context


def refuse_unverifiable(
    mode: str,
    engine: str,
    *,
    connection_id: str | None = None,
    db_type: str | None = None,
) -> None:
    """Refuse a verifying mode on an engine whose driver cannot verify."""
    if mode in VERIFYING_SSL_MODES:
        raise _refuse(
            f"SSL mode '{mode}' is not available for {engine}: this sandbox's driver "
            "cannot verify the server certificate. Use 'require' for an encrypted, "
            "unverified link. Not connecting.",
            connection_id=connection_id,
            db_type=db_type,
        )
