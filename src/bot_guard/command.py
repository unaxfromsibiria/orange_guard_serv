import logging
import typing

from aiogram.types.user import User

from .storage import BaseStorage


class CommandHandler:
    """Command handlers.
    """
    logger: logging.Logger
    storage: BaseStorage

    def __init__(
        self,
        logger: logging.Logger,
        storage: BaseStorage
    ):
        self.logger = logger
        self.storage = storage
        self.storage.logger = logger

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

    def close(self):
        self.storage.sync(force=True)
