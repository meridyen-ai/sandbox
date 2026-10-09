"""
Where a database connection may point.

A connection's host is typed by the person adding it and dialled from inside
the sandbox's own network. Every connector asks here before it dials, so the
rule is the same for a connection test, a schema sync and a query.

Refused:

- this machine and the cloud's instance metadata: loopback, link-local,
  unspecified, multicast and reserved addresses;
- any address on a network the sandbox itself is attached to. Those are the
  platform's own container networks, where its databases and services listen.
  They are read from the sandbox's interfaces when asked; nothing is named or
  configured here.

Allowed:

- everything else, including private ranges (10/8, 172.16/12, 192.168/16) the
  sandbox is not attached to: customer databases on an on-premise network or
  behind a VPN live there. A VPN tunnel is a point-to-point interface, so the
  network behind it is not one of the sandbox's own;
- the sandbox's own upload database server, for the per-upload databases the
  file loader creates (``upload_*``) and nothing else on that server.

A host name is checked on every address it resolves to. Where the driver can
be handed an address, the connector dials the checked address instead of
resolving the name a second time; where it cannot (TLS needs the name), the
connector checks the address it actually reached with :func:`verify_peer`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from typing import Any

from sandbox.core.config import DatabaseType, get_config
from sandbox.core.exceptions import ConnectionError
from sandbox.core.logging import get_logger, log_security_event

logger = get_logger(__name__)

_SIOCGIFFLAGS = 0x8913
_SIOCGIFADDR = 0x8915
_SIOCGIFNETMASK = 0x891B
_IFF_POINTOPOINT = 0x10

# "This network" (RFC 1122): Linux delivers a connection to 0.x.y.z locally.
_THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")

# Where the file loader keeps uploads (see services/file_loader.py).
_UPLOAD_DB_HOST = os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres")
_UPLOAD_DB_PORT = int(os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"))
# The database names file_loader.sanitize_db_name produces.
_UPLOAD_DB_NAME = re.compile(r"upload_[a-z0-9_]{1,56}")

_PORT_SUFFIX = re.compile(r"[,:]\d{1,5}$")

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class VettedHost:
    """The outcome of :func:`vet_destination` for one connection attempt.

    ``addresses`` are the checked addresses of the host, in resolver order.
    It is empty when the policy does not apply to this connection (the upload
    database, or a sandbox configured to allow local destinations); the
    connector then dials the configured host as it always has.
    """

    addresses: tuple[str, ...] = ()

    @property
    def enforced(self) -> bool:
        return bool(self.addresses)


def is_upload_database(cfg: Any) -> bool:
    """True for a connection to a per-upload database on the upload server."""
    db_type = getattr(cfg.db_type, "value", cfg.db_type)
    return (
        db_type == DatabaseType.POSTGRESQL.value
        and (cfg.host or "").strip().lower() == _UPLOAD_DB_HOST.strip().lower()
        and int(cfg.port or 0) == _UPLOAD_DB_PORT
        and _UPLOAD_DB_NAME.fullmatch(cfg.database or "") is not None
    )


def _interface_is_point_to_point(probe: socket.socket, name: str) -> bool:
    import fcntl
    import struct

    request = struct.pack("256s", name.encode()[:15])
    try:
        flags = struct.unpack("H", fcntl.ioctl(probe.fileno(), _SIOCGIFFLAGS, request)[16:18])[0]
    except OSError:
        return False
    return bool(flags & _IFF_POINTOPOINT)


def own_networks() -> list[IPNetwork]:
    """The networks the sandbox's own interfaces sit on, read when asked.

    A point-to-point interface (a VPN tunnel) contributes only its own
    address: the hosts reached through it are the customer's, not ours.
    """
    import fcntl
    import struct

    networks: list[IPNetwork] = []
    point_to_point: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _index, name in socket.if_nameindex():
            p2p = _interface_is_point_to_point(probe, name)
            if p2p:
                point_to_point.add(name)
            request = struct.pack("256s", name.encode()[:15])
            try:
                address = socket.inet_ntoa(
                    fcntl.ioctl(probe.fileno(), _SIOCGIFADDR, request)[20:24]
                )
                netmask = socket.inet_ntoa(
                    fcntl.ioctl(probe.fileno(), _SIOCGIFNETMASK, request)[20:24]
                )
            except OSError:
                continue  # no IPv4 address on this interface
            networks.append(
                ipaddress.ip_network(f"{address}/32" if p2p else f"{address}/{netmask}", strict=False)
            )
    try:
        with open("/proc/net/if_inet6", encoding="ascii") as handle:
            for line in handle:
                fields = line.split()
                if len(fields) < 6:
                    continue
                address = ipaddress.IPv6Address(int(fields[0], 16))
                prefix = 128 if fields[5] in point_to_point else int(fields[2], 16)
                networks.append(ipaddress.ip_network(f"{address}/{prefix}", strict=False))
    except FileNotFoundError:
        pass  # no IPv6 on this host
    return networks


def _refusal(address: IPAddress, networks: list[IPNetwork]) -> str | None:
    """Why ``address`` may not be dialled, or None when it may."""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_loopback or address.is_unspecified or address in _THIS_NETWORK:
        return "it is this machine"
    if address.is_link_local:
        return "it is a link-local address"
    if address.is_multicast or address.is_reserved:
        return "it is not a host address"
    if any(address in network for network in networks):
        return "it is on the platform's own network"
    return None


def _refuse(cfg: Any, reason: str) -> ConnectionError:
    log_security_event(
        "blocked_connection_destination",
        connection_id=cfg.id,
        host=cfg.host,
        reason=reason,
    )
    return ConnectionError(
        f"'{cfg.host}' cannot be used as a data source: {reason}. Not connecting.",
        connection_id=cfg.id,
        db_type=getattr(cfg.db_type, "value", cfg.db_type),
    )


def _lookup_name(host: str) -> str:
    """The name to resolve: brackets off an IPv6 literal, and the instance and
    port off the SQL Server spellings ``host\\instance``, ``host,1433`` and
    ``host:1433``."""
    name = host.strip()
    if name.startswith("[") and name.endswith("]"):
        return name[1:-1]
    name = name.split("\\", 1)[0].strip()
    if name.count(":") <= 1:  # not a bare IPv6 literal
        name = _PORT_SUFFIX.sub("", name)
    return name


async def vet_destination(cfg: Any) -> VettedHost:
    """Check where ``cfg`` points before anything is dialled.

    Raises ``ConnectionError`` when the host is missing, does not resolve, or
    resolves to an address that is refused.
    """
    if get_config().security.allow_local_destinations or is_upload_database(cfg):
        return VettedHost()

    name = _lookup_name(cfg.host or "")
    if not name:
        raise _refuse(cfg, "no host was given")

    try:
        literal: IPAddress | None = ipaddress.ip_address(name)
    except ValueError:
        literal = None

    if literal is not None:
        addresses: list[IPAddress] = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                name, None, type=socket.SOCK_STREAM
            )
        except (socket.gaierror, UnicodeError):
            raise ConnectionError(
                f"Cannot resolve host '{cfg.host}'",
                connection_id=cfg.id,
                db_type=getattr(cfg.db_type, "value", cfg.db_type),
            ) from None
        addresses = []
        for info in infos:
            # A scoped IPv6 address ("fe80::1%eth0") is link-local by definition.
            address = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise ConnectionError(
                f"Cannot resolve host '{cfg.host}'",
                connection_id=cfg.id,
                db_type=getattr(cfg.db_type, "value", cfg.db_type),
            )

    networks = own_networks()
    for address in addresses:
        reason = _refusal(address, networks)
        if reason is not None:
            raise _refuse(cfg, reason)
    return VettedHost(addresses=tuple(str(address) for address in addresses))


def verify_peer(cfg: Any, vetted: VettedHost, peername: Any) -> None:
    """Check the address a connection actually reached.

    For connectors that had to dial the host by name: the name is resolved a
    second time by the driver, and may answer differently than it did for
    :func:`vet_destination`. ``peername`` is the transport's ``peername``.
    Raises ``ConnectionError`` when the peer is refused or cannot be read; the
    caller closes the connection.
    """
    if not vetted.enforced:
        return
    try:
        address = ipaddress.ip_address(str(peername[0]).split("%", 1)[0])
    except (TypeError, IndexError, ValueError):
        raise _refuse(cfg, "the address that was reached could not be checked") from None
    reason = _refusal(address, own_networks())
    if reason is not None:
        raise _refuse(cfg, reason)
