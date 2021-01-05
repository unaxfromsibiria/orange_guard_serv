import logging
import typing
from urllib.parse import urljoin

import aiohttp
from aiogram.types.user import User

from .helpers import env_var_line
from .helpers import env_var_list
from .storage import BaseStorage

TEMP_IMG_URI = env_var_line("TEMP_IMG_URI") or "t/history.jpeg"
TEMP_VAL_URI = env_var_line("TEMP_VAL_URI") or "t"
GPIO_API_URI = env_var_line("GPIO_API_URI") or "gpio"
GPIO_SCHEDULE_API_URI = (
    env_var_line("GPIO_SCHEDULE_API_URI") or "gpio-schedule"
)
PHOTO_EVENTS_URI = env_var_line("PHOTO_EVENTS_URI") or "/photo-events"
# GPIO_CONFIG=air:1 2 4, alarm: 15
GPIO_CONFIG: typing.Dict[str, tuple] = {
    key: tuple(map(int, map(str.strip, gpio_values.split())))
    for key, gpio_values in (
        map(str.strip, part.split(":"))
        for part in env_var_list("GPIO_CONFIG")
    )
    if key
}


class CommandHandler:
    """Command handlers.
    """
    logger: logging.Logger
    storage: BaseStorage
    api_host: str
    temp_api_url: str
    gpio_api_url: str
    gpio_schedule_api_url: str
    photo_event_api_url: str

    def __init__(
        self,
        logger: logging.Logger,
        storage: BaseStorage
    ):
        self.logger = logger
        self.storage = storage
        self.storage.logger = logger
        self.api_host = env_var_line("API_HOST_URL")
        self.gpio_api_url = urljoin(self.api_host, GPIO_API_URI)
        self.gpio_schedule_api_url = urljoin(
            self.api_host, GPIO_SCHEDULE_API_URI
        )
        self.temp_api_url = urljoin(self.api_host, TEMP_IMG_URI)
        self.temp_val_url = urljoin(self.api_host, TEMP_VAL_URI)
        self.photo_event_api_url = urljoin(self.api_host, PHOTO_EVENTS_URI)

    async def execute(
        self, from_client: str, message: str
    ) -> typing.Tuple[str, typing.Optional[bytes]]:
        """Get answer as text and an object.
        """
        return "Unknown message type", None

    async def access(self, user: User) -> bool:
        """Check user access.
        """
        return user.username in self.storage.users

    async def add_user(self, user: str) -> bool:
        """Add user.
        """
        n = len(self.storage.users)
        self.storage.add_user(user)
        return n < len(self.storage.users)

    async def temperature_history(
        self, begin: str, end: str
    ) -> typing.Tuple[str, typing.Optional[bytes]]:
        """Make the request to api.
        """
        data = None
        msg = ""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.temp_api_url, json={"begin": begin, "end": end}
            ) as resp:
                if 200 <= resp.status < 300:
                    data = await resp.read()
                    msg = f"Temperature of period {begin}..{end}"
                else:
                    answer = await resp.text()
                    msg = f"Api answer: {answer}"
                    self.logger.error(msg)

        return msg, data

    async def get_photo_events(self) -> typing.List[str]:
        """Read events from photo detection api.
        """
        result = []
        async with aiohttp.ClientSession() as session:
            async with session.get(self.photo_event_api_url) as resp:
                if 200 <= resp.status < 300:
                    data: dict = await resp.json()
                    if isinstance(data, dict):
                        values: dict = data.get("data")
                        if values and isinstance(values, dict):
                            result.extend(
                                "{}: {}".format(
                                    dt[:19], score
                                )
                                for dt, score in values.items()
                            )
                else:
                    answer = await resp.text()
                    msg = f"Api answer: {answer}"
                    self.logger.error(msg)

        return result

    async def get_temperature(self) -> typing.Optional[float]:
        """Read events from photo detection api.
        """
        result = None
        async with aiohttp.ClientSession() as session:
            async with session.get(self.temp_val_url) as resp:
                if 200 <= resp.status < 300:
                    data: dict = await resp.json()
                    if isinstance(data, dict):
                        temperature: str = data.get("temperature") or ""
                        if temperature:
                            try:
                                val, *_ = temperature.split()
                                result = float(val)
                            except (ValueError, TypeError):
                                pass

                else:
                    answer = await resp.text()
                    msg = f"Api answer: {answer}"
                    self.logger.error(msg)

        return result

    async def update_gpio_state(
        self, group: str, on: bool = True, delay: int = 0
    ) -> bool:
        """Change gpio state via API.
        """
        pins = GPIO_CONFIG.get(group)
        if not pins:
            self.logger.warning(f"Unknown gpio group '{group}'")
            return False

        request = {
            "delay": delay if on else 0,
            "state": on,
            "pins": list(pins)
        }
        result = False
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.gpio_api_url, json=request
            ) as resp:
                if 200 <= resp.status < 300:
                    data: dict = await resp.json()
                    if isinstance(data, dict):
                        errors = data.get("errors")
                        if errors:
                            self.logger.error(
                                f"Gpio group '{group}' api error: {errors}"
                            )
                        else:
                            result = True
                else:
                    answer = await resp.text()
                    msg = f"Api answer: {answer}"
                    self.logger.error(msg)

        return result

    async def update_gpio_air_schedule(
        self, intervals: typing.List[typing.Tuple[str, str]]
    ) -> bool:
        """Change schedule for air GPIO group via API.
        """
        pins = GPIO_CONFIG.get("air")
        if not pins:
            self.logger.warning("Unknown gpio group 'air'")
            return False

        request = {
            "intervals": [
                {"begin": begin, "end": end}
                for begin, end in intervals
            ],
            "pins": list(pins),
            "update": False
        }
        result = False
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.gpio_schedule_api_url, json=request
            ) as resp:
                if 200 <= resp.status < 300:
                    data: dict = await resp.json()
                    if isinstance(data, dict):
                        errors = data.get("errors")
                        if errors:
                            self.logger.error(
                                "Gpio schedule group 'air' "
                                f"api error: {errors}"
                            )
                        else:
                            result = True
                else:
                    answer = await resp.text()
                    msg = f"Api answer: {answer}"
                    self.logger.error(msg)

        return result

    def close(self):
        self.storage.sync(force=True)
