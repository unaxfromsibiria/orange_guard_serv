# run: python -m bot_guard.run
import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram import Dispatcher
from aiogram import executor
from aiogram import types

from .command import CommandHandler
from .const import HELP_MSG
from .const import NOT_ACCESS_ERROR
from .helpers import current_date
from .helpers import env_var_float
from .helpers import env_var_line
from .helpers import env_var_time
from .storage import DataStorage

WATCH_INTERVAL = env_var_time("WATCH_INTERVAL") or 300
TEMP_ALERT_DELTA = env_var_float("TEMP_ALERT_DELTA") or 1
token = env_var_line("BOT_TOKEN")
# # # #
assert token, "Set value for env variable BOT_TOKEN"

bot = Bot(token=token)
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)
status = {"active": True}

handler = CommandHandler(
    logger=logging.getLogger("bot"), storage=DataStorage()
)


async def event_watcher(logger: logging.Logger):
    """Check the API in device to send a notification for users.
    """
    while status.get("active"):
        await asyncio.sleep(WATCH_INTERVAL)
        chat_ids = handler.storage.subscription
        if chat_ids:
            # photo changes
            logger.info(f"Check events for {len(chat_ids)} subscription")
            events = await handler.get_photo_events()
            content = []
            if events:
                msg = "Events detected by photos at: \n{}".format(
                    "\n".join(events)
                )
                content.append(msg)
                logger.warning(f"Photo events: {len(events)}")
            # temperature alert
            temperature = await handler.get_temperature()
            if temperature is not None:
                prev_temperature = handler.storage.get("temperature")
                handler.storage.set("temperature", temperature)
                if prev_temperature is None:
                    logger.info(
                        f"New temperature value in storage {temperature}"
                    )
                else:
                    delta = abs(prev_temperature - temperature)
                    if delta >= TEMP_ALERT_DELTA:
                        msg = (
                            f"Temperature changes too fast: {prev_temperature}"
                            f" -> {temperature}"
                        )
                        content.append(msg)
                        logger.warning(
                            f"temperature {prev_temperature} -> {temperature}"
                        )

            # send
            if content:
                msg = "\n".join(content)
                for chat_id in chat_ids:
                    await bot.send_message(chat_id=chat_id, text=msg)


async def setup_loop(dispatcher):
    handler.storage.sync()
    loop = asyncio.get_running_loop()
    loop.create_task(event_watcher(handler.logger))


@dp.message_handler(commands="help")
async def make_help_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        await message.answer(HELP_MSG)
    else:
        user = f"{message.from_user.full_name}({message.from_user.id})"
        handler.logger.warning(f"User {user} asked 'help'")
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="adduser")
async def make_adduser_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        new_user = message.get_args().strip().strip("@")
        is_new = False
        if new_user:
            is_new = await handler.add_user(new_user)

        is_new = "yes" if is_new else "no"
        await message.answer(
            f"New user '{new_user}' (is new: {is_new})"
        )
    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="temp")
async def make_temp_img_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        days = (message.get_args() or "").split()
        begin = end = None
        if days:
            if len(days) == 2:
                begin, end = days
            elif len(days) == 1:
                begin, *_ = days

        if end is None:
            end = current_date().isoformat()
        if begin is None:
            begin = (current_date() - timedelta(30)).isoformat()

        msg, img_data  = await handler.temperature_history(begin, end)
        if img_data:
            await message.reply_photo(img_data, caption=msg)
        else:
            await message.answer(msg)

    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="events")
async def make_event_subscription_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        cmd = (message.get_args() or "").strip().lower()
        if cmd in ("on", ""):
            msg = "turned on"
            handler.storage.subscription_add(message.chat.id)
        elif cmd == "off":
            msg = "turned off"
            handler.storage.subscription_remove(message.chat.id)
        else:
            msg = f"Unknown argument ({cmd})"
        await message.answer(msg)

    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="start")
async def gpio_api_on(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        args = (message.get_args() or "").strip().lower().split()
        group = ""
        delay = 600
        if len(args) == 1:
            group, *_ = args
        elif len(args) == 2:
            group, delay = args
            delay = int(delay) * 60

        changed = await handler.update_gpio_state(group, True, delay)
        if changed:
            msg = f"Changed GPIO group '{group}'' for {delay} seconds"
        else:
            msg = f"Can't change GPIO group '{group}'"

        await message.answer(msg)
    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="off")
async def gpio_api_off(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        args = (message.get_args() or "").strip().lower().split()
        group = ""
        if len(args) >= 1:
            group, *_ = args

        changed = await handler.update_gpio_state(group, False)
        if changed:
            msg = f"Turned off GPIO group '{group}'"
        else:
            msg = f"Can't change GPIO group '{group}'"

        await message.answer(msg)
    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler()
async def make_answer(message: types.Message):
    """Single enter point.
    """
    user = f"{message.from_user.full_name}({message.from_user.id})"
    accepted = await handler.access(message.from_user)
    if accepted:
        msg, img_data  = await handler.execute(user, message.text)
        if img_data:
            await message.reply_photo(img_data, caption=msg)
        else:
            await message.answer(msg)
    else:
        await message.answer(NOT_ACCESS_ERROR)

try:
    executor.start_polling(
        dp, skip_updates=True, on_startup=setup_loop
    )
finally:
    status.update(active=False)
    handler.close()
