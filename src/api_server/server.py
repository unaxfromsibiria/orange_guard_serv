# OrangePi peripheries access server

import asyncio
import logging
import os
import subprocess
import typing
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .helpers import current_datetime
from .helpers import env_var_bool
from .helpers import env_var_int
from .helpers import env_var_line
from .helpers import env_var_list
from .helpers import env_var_time
from .img import compare_areas
from .img import get_photo_area
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

BOARD_NAME = env_var_line("BOARD_NAME") or "PCPCPLUS"
try:
    import OPi.GPIO as GPIO
except ImportError:
    GPIO = None
else:
    board = int(getattr(GPIO, BOARD_NAME, GPIO.PCPCPLUS))
    GPIO.setboard(board)
    GPIO.setwarnings(True)
    GPIO.setmode(GPIO.BOARD)

REBOOT_ALLOW = env_var_bool("REBOOT_ALLOW")
NETWORK_CHECK_TIMEOUT = env_var_time("NETWORK_CHECK_TIMEOUT") or 600
CAMERA_CHECK_INTERVAL = env_var_int("CAMERA_CHECK_INTERVAL") or 5
# percent 70% by default
IMG_COMPARE_LIMIT = env_var_int("IMG_COMPARE_LIMIT") or 70
PINS = env_var_list("PINS")
DEFAULT_WATCH_ITER_TIME = 1
GPIO_STATA_OFF = True
GPIO_STATA_ON = False

logger = logging.getLogger(env_var_line("LOGGER") or "uvicorn.asgi")


class ServerApp(FastAPI):
    current_state: dict
    ps_executor = ProcessPoolExecutor()


class IntervalParams(BaseModel):
    begin: date
    end: date


class GpioStateParams(BaseModel):
    delay: int = 60
    pins: typing.List[int]
    # set state
    state: bool = True


class TimeIntervalRecord(BaseModel):
    begin: time
    end: time


class GpioScheduleParams(BaseModel):
    intervals: typing.List[TimeIntervalRecord]
    pins: typing.List[int]
    update: bool = True


app = ServerApp()


async def watch_image_changes(state: dict, pool: ProcessPoolExecutor):
    """Compare images.
    """
    loop = asyncio.get_running_loop()
    while state.get("active"):
        try:
            img = await loop.run_in_executor(pool, get_photo_area)
        except Exception as err:
            img = None
            logger.error("Photo getting error: %s", err)
            continue

        prev_img = state.get("last_image")
        state["last_image"] = img
        if not(prev_img is None or img is None):
            prop = compare_areas(prev_img, img)
            if prop < IMG_COMPARE_LIMIT:
                logger.warning(f"Camera changes detected {prop}")
                state["image_events"].append((prop, current_datetime()))

        await asyncio.sleep(CAMERA_CHECK_INTERVAL)


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


async def gpio_watcher(state: dict):
    """Gpio timer.
    """
    on_pins = []
    off_pins = []
    while state.get("active"):
        await asyncio.sleep(DEFAULT_WATCH_ITER_TIME)
        now = current_datetime()
        day = now.date()
        off_pins.clear()
        off_pins.extend(
            pin for pin, limit in (state.get("pins_time") or {}).items()
            if limit and limit < now
        )
        on_pins.clear()
        # from schedule
        for pin, begin_time, end_time in state.get("pins_schedule") or []:
            begin = datetime.combine(day, begin_time)
            end = datetime.combine(day, end_time)
            if begin <= now <= end:
                if pin not in off_pins:
                    on_pins.append(pin)
            else:
                off_pins.append(pin)

        if off_pins:
            for pin in off_pins:
                if not state["pins"][pin]:
                    continue

                try:
                    GPIO.output(pin, GPIO_STATA_OFF)
                    if pin in state["pins_time"]:
                        del state["pins_time"][pin]
                except Exception as err:
                    logger.error(f"Problem with PIN {pin}: {err}")
                    continue

                logger.info(f"PIN {pin} turned off automatically")
                state["pins"][pin] = False

        if on_pins:
            for pin in on_pins:
                if state["pins"][pin]:
                    continue

                try:
                    GPIO.output(pin, GPIO_STATA_ON)
                except Exception as err:
                    logger.error(f"Problem with PIN {pin}: {err}")
                    continue

                logger.info(f"PIN {pin} turned on automatically by schedule")
                state["pins"][pin] = True


@app.on_event("startup")
async def initial_task():
    """Background logic.
    """
    app.ps_executor = ProcessPoolExecutor(
        max_workers=env_var_int("WORKERS_PS_EXECUTER") or 4
    )
    logger.info(f"Pins: {PINS}")
    pins = list(map(int, PINS))
    PINS.clear()
    PINS.extend(pins)
    app.current_state = {
        "active": True,
        "last_image": None,
        "image_events": [],
        "pins": {pin: False for pin in pins},
        "pins_time": {},
        "pins_schedule": []
    }
    if GPIO:
        for pin in pins:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO_STATA_OFF)

    logger.info("Setup service tasks..")
    loop = asyncio.get_running_loop()
    loop.create_task(temperature_watcher(app.current_state))
    loop.create_task(temperature_storage_watcher(app.current_state))
    loop.create_task(network_watcher(app.current_state))
    loop.create_task(watch_image_changes(app.current_state, app.ps_executor))
    loop.create_task(gpio_watcher(app.current_state))


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
async def temperature_history_api(intval: IntervalParams):
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
async def temperature_history_api_jpeg(intval: IntervalParams):
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


@app.get("/photo-events")
async def photo_events_api():
    """Events from camera.
    """
    result = {"data": {
        dt.isoformat(): value
        for value, dt in app.current_state["image_events"]
    }}
    app.current_state["image_events"].clear()
    return result


@app.post("/gpio")
async def gpio_state_api(state: GpioStateParams):
    """Set state and timer limit for PINs.
    """
    errors = []
    changed = 0
    for pin in state.pins:
        if pin not in PINS:
            errors.append(f"Unsupported PIN: {pin}")
            continue

        if app.current_state["pins"][pin] == state.state:
            continue

        try:
            GPIO.output(
                pin,
                GPIO_STATA_ON if state.state else GPIO_STATA_OFF
            )
        except Exception as err:
            msg = f"Pin {pin} error: {err}"
            logger.error(msg)
            errors.append(msg)
            continue

        dt = current_datetime() + timedelta(seconds=state.delay)
        try:
            app.current_state["pins"][pin] = state.state
            app.current_state["pins_time"][pin] = dt
        except Exception as err:
            logger.critical(
                f"State {app.current_state} error: {err}"
            )
            errors.append(f"State error: {err}")
        else:
            changed += 1
            logger.info(f"PIN {pin} will back state at {dt}")

    result = {"changed": changed}
    if errors:
        result["errors"] = errors

    return result


@app.get("/gpio-state")
async def gpio_state_info():
    """App state of gpio.
    """
    return {
        field: app.current_state.get(field)
        for field in ("pins", "pins_schedule", "pins_time")
    }


@app.post("/gpio-schedule")
async def gpio_state_schedule_api(options: GpioScheduleParams):
    """Set schedule for PINs.
    """
    errors = []
    result = {}
    new_state = []
    if options.update:
        for pin, start, end in app.current_state["pins_schedule"]:
            if pin not in new_state:
                new_state.append((pin, start, end))

    for pin in options.pins:
        if pin not in PINS:
            errors.append(f"Unsupported PIN: {pin}")
            continue

        for interval in options.intervals:
            new_state.append((pin, interval.begin, interval.end))

    app.current_state["pins_schedule"] = new_state
    result["schedule"] = new_state
    if errors:
        result["errors"] = errors

    return result
