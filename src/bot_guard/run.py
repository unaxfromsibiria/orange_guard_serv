# run: python -m bot_guard.run
import logging

from aiogram import Bot
from aiogram import Dispatcher
from aiogram import executor
from aiogram import types

from .command import CommandHandler
from .const import HELP_MSG
from .const import NOT_ACCESS_ERROR
from .helpers import env_var_line
from .storage import DataStorage

bot = Bot(token=env_var_line("BOT_TOKEN"))
dp = Dispatcher(bot)
logging.basicConfig(level=logging.INFO)

handler = CommandHandler(
    logger=logging.getLogger("bot"), storage=DataStorage()
)


async def setup_loop(dispatcher):
    handler.storage.sync()


@dp.message_handler(commands="help")
async def make_help_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        await message.answer(HELP_MSG)
    else:
        await message.answer(NOT_ACCESS_ERROR)


@dp.message_handler(commands="adduser")
async def make_adduser_answer(message: types.Message):
    accepted = await handler.access(message.from_user)
    if accepted:
        new_user = message.get_args()
        is_new = False
        if new_user:
            is_new = await handler.add_user(new_user)

        is_new = "yes" if is_new else "no"
        await message.answer(
            f"New user '{new_user}' (is new: {is_new})"
        )
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
    handler.close()
