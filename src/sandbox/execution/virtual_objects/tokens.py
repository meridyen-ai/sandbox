"""
Parameter values for procedure-backed virtual objects.

A parameter value is either a literal or ONE whole-value date token such as
``{{today}}``, ``{{start_of_month}}`` or ``{{start_of_year-1y}}``. Tokens are
resolved at execution time in the connection's timezone, then converted to the
parameter's SQL type. Values are always bound as parameters or emitted as AST
literals — never spliced into SQL text.
"""

from __future__ import annotations

import os
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.models import ParamSpec

TOKENS: dict[str, str] = {
    "today": "Current date",
    "now": "Current date and time",
    "yesterday": "Previous day",
    "start_of_week": "Monday of the current week",
    "start_of_month": "First day of the current month",
    "end_of_month": "Last day of the current month",
    "start_of_prev_month": "First day of the previous month",
    "end_of_prev_month": "Last day of the previous month",
    "start_of_quarter": "First day of the current quarter",
    "start_of_year": "January 1st of the current year",
    "end_of_year": "December 31st of the current year",
    "start_of_prev_year": "January 1st of the previous year",
    "end_of_prev_year": "December 31st of the previous year",
    "year": "Current year as a number (e.g. {{year-1y}} for last year)",
    "last_3_years": "Comma-separated list of the last 3 years, this year included",
    "last_5_years": "Comma-separated list of the last 5 years, this year included",
}

# {{last_<N>_years}} works for any N from 1 to 20; the catalogue lists two.
_LAST_YEARS_RE = re.compile(r"^last_(\d{1,2})_years$")

_TOKEN_RE = re.compile(
    r"^\{\{\s*(?P<name>[a-z0-9_]+)\s*(?:(?P<sign>[+-])\s*(?P<n>\d+)\s*(?P<unit>[dwmy]))?\s*\}\}$"
)


def is_token(value: str | None) -> bool:
    return bool(value) and bool(_TOKEN_RE.match(value.strip()))


def resolve_timezone(extra_params: dict[str, Any] | None) -> ZoneInfo:
    name = (extra_params or {}).get("timezone") or os.environ.get(
        "SANDBOX_DEFAULT_TIMEZONE", "UTC"
    )
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return d.replace(year=year, month=month, day=min(d.day, monthrange(year, month)[1]))


def _base(name: str, now: datetime) -> date | datetime | int | str:
    today = now.date()
    if name == "year":
        return today.year
    m = _LAST_YEARS_RE.match(name)
    if m and 1 <= int(m.group(1)) <= 20:
        n = int(m.group(1))
        return ",".join(str(y) for y in range(today.year - n + 1, today.year + 1))
    if name == "now":
        return now.replace(tzinfo=None, microsecond=0)
    if name == "today":
        return today
    if name == "yesterday":
        return today - timedelta(days=1)
    if name == "start_of_week":
        return today - timedelta(days=today.weekday())
    if name == "start_of_month":
        return today.replace(day=1)
    if name == "end_of_month":
        return today.replace(day=monthrange(today.year, today.month)[1])
    if name == "start_of_prev_month":
        return _add_months(today.replace(day=1), -1)
    if name == "end_of_prev_month":
        return today.replace(day=1) - timedelta(days=1)
    if name == "start_of_quarter":
        return date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    if name == "start_of_year":
        return date(today.year, 1, 1)
    if name == "end_of_year":
        return date(today.year, 12, 31)
    if name == "start_of_prev_year":
        return date(today.year - 1, 1, 1)
    if name == "end_of_prev_year":
        return date(today.year - 1, 12, 31)
    raise VirtualObjectError(f"Unknown token '{{{{{name}}}}}'")


def resolve_token(value: str, now: datetime) -> date | datetime | int | str:
    m = _TOKEN_RE.match(value.strip())
    if not m:
        raise VirtualObjectError(f"Invalid token '{value}'")
    result = _base(m.group("name"), now)
    if isinstance(result, str):
        if m.group("sign"):
            raise VirtualObjectError(f"'{value}': year lists take no offset")
        return result
    if isinstance(result, int):
        if m.group("sign"):
            if m.group("unit") != "y":
                raise VirtualObjectError(f"'{value}': offset a year by years (e.g. -1y)")
            n = int(m.group("n"))
            result = result + (n if m.group("sign") == "+" else -n)
        return result
    if m.group("sign"):
        n = int(m.group("n")) * (1 if m.group("sign") == "+" else -1)
        unit = m.group("unit")
        if unit == "d":
            result = result + timedelta(days=n)
        elif unit == "w":
            result = result + timedelta(weeks=n)
        elif unit == "m":
            result = _add_months(result, n) if not isinstance(result, datetime) else datetime.combine(
                _add_months(result.date(), n), result.time()
            )
        elif unit == "y":
            result = _add_months(result, 12 * n) if not isinstance(result, datetime) else datetime.combine(
                _add_months(result.date(), 12 * n), result.time()
            )
    return result


def _type_family(sql_type: str) -> str:
    t = (sql_type or "").strip().lower()
    base = re.split(r"[\s(]", t, maxsplit=1)[0] if t else ""
    if base in ("date",):
        return "date"
    if base in ("datetime", "datetime2", "smalldatetime", "datetimeoffset", "timestamp", "timestamptz"):
        return "datetime"
    if base in ("int", "integer", "bigint", "smallint", "tinyint", "int2", "int4", "int8", "serial", "bigserial"):
        return "int"
    if base in ("decimal", "numeric", "money", "smallmoney"):
        return "decimal"
    if base in ("float", "real", "double", "float4", "float8"):
        return "float"
    if base in ("bit", "bool", "boolean"):
        return "bool"
    return "str"


def convert_value(raw: str | None, sql_type: str, now: datetime) -> Any:
    """Literal or token → Python value of the parameter's type."""
    if raw is None:
        return None
    family = _type_family(sql_type)
    text = raw.strip()
    try:
        if is_token(text):
            v = resolve_token(text, now)
            if isinstance(v, (int, str)):
                # {{year}} / {{last_N_years}}: a number or a list, not a date.
                if family == "int":
                    return int(v) if isinstance(v, int) else int(str(v).split(",")[-1])
                if family in ("date", "datetime"):
                    raise VirtualObjectError(f"'{raw}' is not a date; use a date token")
                return str(v)
            if family == "date":
                return v.date() if isinstance(v, datetime) else v
            if family == "datetime":
                return v if isinstance(v, datetime) else datetime.combine(v, time.min)
            return v.isoformat()
        if text == "" and family != "str":
            return None
        if family == "date":
            return date.fromisoformat(text[:10])
        if family == "datetime":
            return datetime.fromisoformat(text.replace("Z", ""))
        if family == "int":
            return int(text)
        if family == "decimal":
            return Decimal(text)
        if family == "float":
            return float(text)
        if family == "bool":
            if text.lower() in ("1", "true", "yes", "y"):
                return True
            if text.lower() in ("0", "false", "no", "n"):
                return False
            raise ValueError(text)
        return raw
    except (ValueError, InvalidOperation) as e:
        raise VirtualObjectError(
            f"Value '{raw}' is not a valid {family} for type '{sql_type or 'text'}'"
        ) from e


@dataclass(frozen=True)
class ResolvedParam:
    name: str
    sql_type: str
    value: Any


def resolve_params(specs: list[ParamSpec], now: datetime) -> list[ResolvedParam]:
    """Resolve every non-omitted parameter, in declaration order."""
    return [
        ResolvedParam(p.name, p.sql_type, convert_value(p.value, p.sql_type, now))
        for p in specs
        if not p.omit
    ]


def now_in(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def describe_tokens(now: datetime) -> list[dict[str, Any]]:
    """Token catalogue with current values, for the UI."""
    def _show(v: Any) -> str:
        return v.isoformat() if isinstance(v, (date, datetime)) else str(v)

    return [
        {"token": f"{{{{{name}}}}}", "description": desc, "value": _show(_base(name, now))}
        for name, desc in TOKENS.items()
    ]
