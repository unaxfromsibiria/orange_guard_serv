import asyncio
import logging
import os
import typing
from datetime import date
from datetime import datetime
from datetime import timedelta

import pandas as pd

from .helpers import current_date
from .helpers import current_datetime
from .helpers import env_var_int
from .helpers import env_var_line
from .helpers import env_var_time

TEMPERATURE_STORAGE = env_var_line("TEMPERATURE_STORAGE") or "/data/temperature"  # noqa
# in mb default 150 mb
TEMPERATURE_STORAGE_MAX_SIZE = env_var_int("TEMPERATURE_STORAGE_MAX_SIZE") or 150  # noqa
# sensor
TEMPERATURE_DEVICE = env_var_line("TEMPERATURE_DEVICE") or "/sys/bus/w1/devices/w1_bus_master1/28-fc6db0116461/w1_slave"  # noqa
TEMPERATURE_READ_INTERVAL = env_var_time("TEMPERATURE_READ_INTERVAL") or 30  # noqa
logger = logging.getLogger(env_var_line("LOGGER") or "uvicorn.asgi")


def read_temperature() -> typing.Optional[float]:
    """Get the current temperature value in C.
        73 01 ff ff 7f ff ff ff 86 : crc=86 YES
        73 01 ff ff 7f ff ff ff 86 t=23187
    """
    result = None
    try:
        with open(TEMPERATURE_DEVICE) as t_file:
            data = t_file.read()
        for part in data.split():
            if "t=" in part:
                result = float(part.replace("t=", "")) / 1000
                break
    except Exception:
        pass

    return result


def current_temperature_filepath(
    dt: typing.Union[date, datetime, None] = None
) -> str:
    file_name, *_ = (dt or current_date()).isoformat().rsplit("-", 1)
    return os.path.join(
        TEMPERATURE_STORAGE, f"month_t_{file_name}.csv"
    )


def save_tempearture() -> bool:
    """Save record to file.
    """
    value = read_temperature()
    if value is None:
        logger.error(f"Sensor value: {value}")
        return False

    filepath = current_temperature_filepath()
    try:
        with open(filepath, "a") as out:
            out.write(f"{current_datetime()},{value:0.2f}\n")
    except Exception as err:
        logger.critical(
            f"Error write value in '{filepath}': {err}"
        )
        return False

    return True


def clear_tempearture_storage():
    """Remove old files.
    """
    one_month = timedelta(days=31)
    files = []
    dt = current_datetime()
    exists_file = True
    while exists_file:
        file_path = current_temperature_filepath(dt)
        dt -= one_month
        exists_file = os.path.exists(file_path)
        if exists_file:
            files.append(file_path)

    files.reverse()
    logger.info(f"Files in storage: {len(files)}")
    size = TEMPERATURE_STORAGE_MAX_SIZE + 1
    while files and size > TEMPERATURE_STORAGE_MAX_SIZE:
        size = sum(map(os.path.getsize, files)) / (1024 ** 2)
        if size > TEMPERATURE_STORAGE_MAX_SIZE:
            old_filepath, *_ = files
            files = files[1:]
            logger.warning(f"Delete old temperature file '{old_filepath}'")
            os.remove(old_filepath)
        else:
            logger.info(f"Current temperature storage size: {size}")


def cpu_temperature() -> float:
    """Read CPU temperature in C.
    """
    cpu_t = 0
    try:
        with open("/sys/devices/virtual/thermal/thermal_zone0/temp") as ff:
            cpu_t = round(float(ff.read().strip()) / 1000, 2)
    except Exception as err:
        logger.error(err)
        cpu_t = 0

    return cpu_t


def read_temperature_history(
    begin: date, end: date
) -> pd.DataFrame:
    """Temperature in time interval as DataFrame
    """
    this_m = begin
    to_next = True
    data = []
    while to_next:
        filepath = current_temperature_filepath(this_m)
        this_m = this_m.replace(day=1) + timedelta(days=31)
        to_next = this_m < end
        if os.path.exists(filepath):
            part = pd.read_csv(filepath)
            part.columns = ["dt", "value"]
            data.append(part)

    n = len(data)
    if n == 0:
        result = pd.DataFrame(data=[], columns=["dt", "value"])
    elif n == 1:
        result, *_ = data
    else:
        result: pd.DataFrame = pd.concat(data, ignore_index=True)

    result.dt = result.dt.astype("datetime64")
    data.clear()
    result = result[(result.dt >= begin) & (result.dt < end + timedelta(1))]
    result.sort_values("dt", inplace=True)
    return result
