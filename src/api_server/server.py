# OrangePi peripheries access server
# fastapi==0.61.2
# uvicorn==0.12.2
# uvloop==0.14.0

import asyncio
import logging
import os
import subprocess
import typing
from datetime import date
from datetime import datetime
from datetime import timedelta

from fastapi import FastAPI
from genericpath import exists

from .helpers import current_date, env_var_bool
from .helpers import current_datetime
from .helpers import env_var_float
from .helpers import env_var_int
from .helpers import env_var_line
from .helpers import env_var_time
from .network_check import check

REBOOT_ALLOW = env_var_bool("REBOOT_ALLOW")
NETWORK_CHECK_TIMEOUT = env_var_time("NETWORK_CHECK_TIMEOUT") or 600

TEMPERATURE_STORAGE = env_var_line("TEMPERATURE_STORAGE") or "/data/temperature"  # noqa
# in mb default 150 mb
TEMPERATURE_STORAGE_MAX_SIZE = env_var_int("TEMPERATURE_STORAGE_MAX_SIZE") or 150  # noqa
# sensor
TEMPERATURE_DEVICE = env_var_line("TEMPERATURE_DEVICE") or "/sys/bus/w1/devices/w1_bus_master1/28-fc6db0116461/w1_slave"  # noqa
TEMPERATURE_READ_INTERVAL = env_var_time("TEMPERATURE_READ_INTERVAL") or 30  # noqa
logger = logging.getLogger("uvicorn.asgi")


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


def current_temperature_filepath(dt: typing.Optional[datetime] = None) -> str:
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


class ServerApp(FastAPI):
    current_state: dict


app = ServerApp()


async def temperature_watcher(state: dict):
    """Record values from sensor to storage.
    """
    while state.get("active"):
        await asyncio.sleep(TEMPERATURE_READ_INTERVAL)
        save_tempearture()


async def temperature_storage_watcher(state: dict):
    """Check size of temperature storage.
    """
    while state.get("active"):
        try:
            clear_tempearture_storage()
        except Exception as err:
            logger.critical(f"Storage clear error: {err}")

        await asyncio.sleep(3600 * 12)


async def network_watcher(state: dict):
    """Global access checking.
    """
    while state.get("active"):
        need_reboot = not check(logger)
        if need_reboot:
            logger.warning(
                "The global Internet is not available. "
                f"Waiting {NETWORK_CHECK_TIMEOUT // 2}"
            )
            await asyncio.sleep(NETWORK_CHECK_TIMEOUT // 2)
            need_reboot = not check(logger)
            if need_reboot:
                if REBOOT_ALLOW:
                    logger.warning("Reboot")
                    os.system("reboot")
                else:
                    logger.warning("Need reboot")
            else:
                logger.warning("Global Internet is available again.")

        await asyncio.sleep(NETWORK_CHECK_TIMEOUT)


@app.on_event("startup")
async def initial_task():
    """Background logic.
    """
    app.current_state = {"active": True}
    logger.info("Setup service tasks..")
    loop = asyncio.get_running_loop()
    loop.create_task(temperature_watcher(app.current_state))
    loop.create_task(temperature_storage_watcher(app.current_state))
    loop.create_task(network_watcher(app.current_state))


@app.get("/")
async def root_page_api():
    result = subprocess.run(["uname", "-a"], capture_output=True, text=True)
    return {"os": f"{result.stdout}".strip()}


@app.get("/t")
async def temperature_api():
    value = read_temperature()
    if value is None:
        result = None
    else:
        result = f"{round(value, 2):0.2f} C"

    return {"temperature": result}


@app.get("/check-internet")
async def check_internet_api():
    return {
        "ok": check(logger)
    }
