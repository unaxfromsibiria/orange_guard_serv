import os
import re
import typing
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from time import monotonic as current_time
from uuid import UUID

time_rx = re.compile(r"([0-9.]+)(\w+)")
YEAR_SECONDS = 3600 * 24 * 365.2425
LONG_DELAY = 2


def env_var_line(key: str) -> str:
    """Reading a environment variable as text.
    """
    return str(os.environ.get(key) or "").strip()


def env_var_int(key: str) -> int:
    """Reading a environment variable as int.
    """
    try:
        return int(env_var_line(key))
    except (ValueError, TypeError):
        return 0


def env_var_float(key: str) -> float:
    """Reading a environment variable as float.
    """
    try:
        return float(env_var_line(key))
    except (ValueError, TypeError):
        return 0


def env_var_bool(key: str) -> bool:
    """Reading a environment variable as binary.
    """
    return env_var_line(key).upper() in (
        "TRUE", "ON", "YES", "OK"
    )


def env_var_uuid(key: str) -> typing.Union[UUID, None]:
    """Reading a environment variable as binary.
    """
    try:
        return UUID(
            env_var_line(key).lower().replace("-", "")
        )
    except (ValueError, TypeError):
        return None


def env_var_time(key: str) -> float:
    """Reading a environment variable as time in seconds.
    VAR=2.5min
    VAR=60
    VAR=1h
    VAR=7days
    VAR=0.5year
    """
    value = env_var_line(key).upper()
    result = env_var_float(value)
    if result:
        return result
    else:
        search = time_rx.match(value)
        if search:
            val, unit = search.groups()
            result = float(val)
            if unit in ("M", "MIN"):
                result *= 60
            elif unit in ("H", "HOUR", "HOURS"):
                result *= 3600
            elif unit in ("D", "DAY", "DAYS"):
                result *= 3600 * 24
            elif unit in ("Y", "YEAR", "YEARS"):
                result *= YEAR_SECONDS

    return result


def env_var_list(key: str, with_type: type = int) -> list:
    """Reading a environment variable as list,
    source line should be divided by commas.
    VAR_NAME=1,233,4,5
    """
    result = list(filter(
        None, map(str.strip, env_var_line(key).split(","))
    ))
    try:
        return list(map(with_type, result))
    except (ValueError, TypeError):
        return result


def current_datetime() -> datetime:
    return datetime.now()


def current_date() -> date:
    return current_datetime().date()
