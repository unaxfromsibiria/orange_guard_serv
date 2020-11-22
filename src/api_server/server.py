# OrangePi peripheries access server

import asyncio
import logging
import os
import subprocess
import typing
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from datetime import datetime
from datetime import timedelta

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .helpers import current_date
from .helpers import current_datetime
from .helpers import env_var_bool
from .helpers import env_var_float
from .helpers import env_var_int
from .helpers import env_var_line
from .helpers import env_var_time
from .helpers import env_var_uuid
from .img import get_png_photo
from .img import png_img_to_base64
from .img import png_img_to_buffer
from .img import table_to_image
from .network_check import check
from .temperature import TEMPERATURE_READ_INTERVAL
from .temperature import clear_tempearture_storage
from .temperature import cpu_temperature
from .temperature import read_temperature
from .temperature import read_temperature_history
from .temperature import save_tempearture

REBOOT_ALLOW = env_var_bool("REBOOT_ALLOW")
NETWORK_CHECK_TIMEOUT = env_var_time("NETWORK_CHECK_TIMEOUT") or 600

logger = logging.getLogger(env_var_line("LOGGER") or "uvicorn.asgi")


class ServerApp(FastAPI):
    current_state: dict
    ps_executor = ProcessPoolExecutor()


class IntervalPrams(BaseModel):
    begin: date
    end: date


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
    app.ps_executor = ProcessPoolExecutor(
        max_workers=env_var_int("WORKERS_PS_EXECUTER") or 2
    )
    app.current_state = {"active": True}
    logger.info("Setup service tasks..")
    loop = asyncio.get_running_loop()
    loop.create_task(temperature_watcher(app.current_state))
    loop.create_task(temperature_storage_watcher(app.current_state))
    loop.create_task(network_watcher(app.current_state))


@app.on_event("shutdown")
async def close_app():
    """Off all.
    """
    try:
        app.ps_executor.shutdown(cancel_futures=True)
    except Exception as err:
        logger.error(f"Close executer error: {err}")


@app.get("/")
async def root_page_api():
    result = subprocess.run(["uname", "-a"], capture_output=True, text=True)
    return {
        "os": f"{result.stdout}".strip(),
        "cpu_temperature": cpu_temperature()
    }


@app.get("/t")
async def temperature_api():
    value = read_temperature()
    if value is None:
        result = None
    else:
        result = f"{round(value, 2):0.2f} C"

    return {"temperature": result}


def create_temperature_history_list(begin: date, end: date) -> list:
    """List of values of temperature log.
    """
    data = read_temperature_history(begin, end)
    return [
        [dt.to_pydatetime().isoformat(), float(val)]
        for dt, val in data.itertuples(index=False)
    ]


def create_temperature_history_chart(
    begin: date, end: date, resample: str = "60min"
):
    """Image data as io buffer.
    """
    data = read_temperature_history(begin, end)
    data.columns = ["dt", "temperature"]
    data.set_index("dt", inplace=True)
    row_data = data.resample(resample).mean()
    row_data.temperature.interpolate(method="linear", inplace=True)
    row_data.temperature.interpolate(method="ffill", inplace=True)
    row_data.temperature.interpolate(method="bfill", inplace=True)
    buffer = table_to_image(row_data, titile=f"Temperature {begin}-{end}")
    return buffer


@app.post("/t/history")
async def temperature_history_api(intval: IntervalPrams):
    """Log of temperature of time interval.
    """
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        app.ps_executor,
        create_temperature_history_list,
        intval.begin,
        intval.end
    )
    return {"history": data}


@app.post("/t/history.jpeg")
async def temperature_history_api_jpeg(intval: IntervalPrams):
    """Log of temperature of time interval as chart.
    """
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        app.ps_executor,
        create_temperature_history_chart,
        intval.begin,
        intval.end
    )
    return StreamingResponse(data, media_type="image/jpeg")


@app.get("/check-internet")
async def check_internet_api():
    return {
        "ok": check(logger)
    }


@app.get("/photo.png")
async def make_photo():
    """Photo from web camera.
    """
    loop = asyncio.get_running_loop()
    img = await loop.run_in_executor(app.ps_executor, get_png_photo)
    if img:
        result = StreamingResponse(
            png_img_to_buffer(img), media_type="image/png"
        )
    else:
        result = HTTPException(status_code=404, detail="Camera not available")

    return result


@app.get("/photo.json")
async def make_json_photo():
    """Photo from web camera in base64.
    """
    img = get_png_photo()
    if img:
        result = {"image": png_img_to_base64(img)}
    else:
        result = {"error": "Camera not available"}

    return result
