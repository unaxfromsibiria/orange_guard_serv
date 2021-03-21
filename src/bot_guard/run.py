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
from .helpers import current_date
from .helpers import env_var_float
from .helpers import env_var_line
from .helpers import env_var_time
from .storage import DataStorage

WATCH_INTERVAL = env_var_time("WATCH_INTERVAL") or 300
SERVICE_TIMEOUT = 0.1
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
    content = []
    while status.get("active"):
        await asyncio.sleep(WATCH_INTERVAL)
        data = None
        subscription = handler.storage.subscription
        if not subscription:
            continue

        # photo changes
        logger.info(f"Check events for {len(subscription)} subscription")
        events = await handler.get_photo_events()
        if events:
            msg = "Events detected by photos at: \n{}".format(
                "\n".join(events)
            )
            content.append(msg)
            logger.warning(f"Photo events: {len(events)}")
            data = await handler.last_image()

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
                        "Temperature changes too fast: "
                        f"{prev_temperature} -> {temperature}"
                    )
                    content.append(msg)
                    logger.warning(
                        "temperature "
                        f"{prev_temperature} -> {temperature}"
                    )

        # send
        if content:
            msg = "\n".join(content)
            content.clear()
            for user, chat_id in subscription:
                accepted = await handler.access(user)
                if not accepted:
                    logger.warning(
                        f"User {user} is not allow for event"
                    )
                    continue

                if data:
                    send_task = bot.send_photo(
                        chat_id=chat_id, photo=data, caption=msg
                    )
                else:
                    send_task = bot.send_message(
                        chat_id=chat_id, text=msg
                    )

                try:
                    await send_task
                except Exception as err:
                    logger.error(
                        f"Send bot error to {chat_id}: {err}"
                    )
                    break
                else:
                    await asyncio.sleep(SERVICE_TIMEOUT)


async def setup_loop(dispatcher):
    handler.storage.sync()
    loop = asyncio.get_running_loop()
    loop.create_task(event_watcher(handler.logger))


@dp.message_handler(commands="help")
@handler.access_check
async def make_help_answer(message: types.Message, **kwargs):
    await message.answer(HELP_MSG)


@dp.message_handler(commands="adduser")
@handler.access_check
async def make_adduser_answer(message: types.Message, **kwargs):
    new_user = message.get_args().strip().strip("@")
    is_new = False
    if new_user:
        is_new = await handler.add_user(new_user)

    is_new = "yes" if is_new else "no"
    await message.answer(f"New user '{new_user}' (is new: {is_new})")


@dp.message_handler(commands="deluser")
@handler.access_check
async def make_deluser_answer(message: types.Message, **kwargs):
    new_user = message.get_args().strip().strip("@")
    is_del = False
    if new_user:
        is_del = await handler.del_user(new_user)

    is_del = "yes" if is_del else "no"
    await message.answer(
        f"User '{new_user}' deleted: {is_del}"
    )


@dp.message_handler(commands="temp")
@handler.access_check
async def make_temp_img_answer(message: types.Message, **kwargs):
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


@dp.message_handler(commands="photo")
@handler.access_check
async def make_photo_img_answer(message: types.Message, **kwargs):
    img_data = await handler.make_photo()
    if img_data:
        await message.reply_photo(img_data, caption="")
    else:
        await message.answer("a problem to get photo")


@dp.message_handler(commands="events")
@handler.access_check
async def make_event_subscription_answer(message: types.Message, **kwargs):
    user = message.from_user
    cmd = (message.get_args() or "").strip().lower()
    if cmd in ("on", ""):
        msg = "turned on"
        handler.storage.subscription_add(
            str(user.username or user.id), message.chat.id
        )
    elif cmd == "off":
        msg = "turned off"
        handler.storage.subscription_remove(message.chat.id)
    else:
        msg = f"Unknown argument ({cmd})"

    await message.answer(msg)


@dp.message_handler(commands="start")
@handler.access_check
async def gpio_api_on(message: types.Message, **kwargs):
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


@dp.message_handler(commands="off")
@handler.access_check
async def gpio_api_off(message: types.Message, **kwargs):
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


@dp.message_handler(commands="air-time")
@handler.access_check
async def gpio_api_air_time(message: types.Message, **kwargs):
    intervals = (message.get_args() or "").strip().lower().split()
    data = []
    for line in intervals:
        if line and "-" in line:
            row = line.split("-")
            if len(row) == 2:
                begin, end = row
                if len(begin) == len(end):
                    data.append((begin, end))

    changed = await handler.update_gpio_air_schedule(data)
    if changed:
        msg = "New air GPIO group schedule"
    else:
        msg = f"Can't change GPIO schedule for intervals {data}"

    await message.answer(msg)


@dp.message_handler()
@handler.access_check
async def make_answer(message: types.Message, **kwargs):
    """Single enter point.
    """
    user = f"{message.from_user.full_name}({message.from_user.id})"
    msg, img_data  = await handler.execute(user, message.text)
    if img_data:
        await message.reply_photo(img_data, caption=msg)
    else:
        await message.answer(msg)


try:
    executor.start_polling(
        dp, skip_updates=True, on_startup=setup_loop
    )
finally:
    status.update(active=False)
    handler.close()


@dp.message_handler(commands="restart")
@handler.access_check
async def restart_api(message: types.Message, **kwargs):
    done = await handler.restart_api_server()
    if done:
        msg = "The server is restarting.."
    else:
        msg = "The function is not available"

    await message.answer(msg)
