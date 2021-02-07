import json
import logging
import typing
import uuid
from datetime import datetime
from datetime import timedelta
from os import stat

from .helpers import current_datetime
from .helpers import env_var_line
from .helpers import env_var_list
from .helpers import env_var_time

DUMP_UPDATE_TIME = timedelta(
    seconds=env_var_time("DUMP_UPDATE_TIME") or 60
)

DEFAULT_USERS = env_var_list("DEFAULT_USERS")


class BaseStorage:
    """Process data
    """
    last_update: datetime
    data: typing.Dict[str, typing.Any]
    logger: logging.Logger

    def __init__(self):
        self.data = {
            "state": uuid.uuid4().hex,
            "values": {},
            "users": DEFAULT_USERS,
            "subscription": [],
        }

        self.last_update = current_datetime() - DUMP_UPDATE_TIME

    def sync(self, force: bool = False):
        """Sync data.
        """
        pass

    def update(self, **optios) -> typing.Any:
        """Setup data values.
        """
        self.data["values"].update(optios)
        self.sync()

    def set(self, key: str, value: typing.Any):
        self.data["values"][key] = value
        self.sync()

    def get(self, key: str) -> typing.Any:
        self.sync()
        return self.data["values"].get(key)

    @property
    def users(self) -> typing.List[str]:
        self.sync()
        return self.data["users"]

    def add_user(self, user: str):
        """Add user.
        """
        data = set(self.data["users"])
        data.add(user)
        self.data["users"] = sorted(data)
        self.sync()

    def delete_user(self, user: str):
        """Delete user.
        """
        data = set(self.data["users"])
        if user in data:
            data.remove(user)
            self.data["users"] = sorted(data)
            self.sync()

    @property
    def subscription(self) -> typing.List[typing.Tuple[str, int]]:
        return [
            tuple(item)
            for item in self.data.get("subscription") or []
            if item and isinstance(item, (list, tuple)) and len(item) == 2
        ]

    def subscription_add(self, user: str, chat_id: int):
        """Add chat id to subscription.
        """
        subscription_set = set(
            tuple(item)
            for item in self.data.get("subscription") or []
            if item and isinstance(item, (list, tuple)) and len(item) == 2
        )

        n = len(subscription_set)
        subscription_set.add((user, chat_id))
        if n < len(subscription_set):
            self.logger.info(f"new chat {chat_id} in events subscription")
            self.data["subscription"] = sorted(subscription_set)
            self.sync(force=True)

    def subscription_remove(self, chat_id: int):
        """Remove chat id from subscription.
        """
        subscription_set = set(
            tuple(item)
            for item in self.data.get("subscription") or []
            if item and isinstance(item, (list, tuple)) and len(item) == 2
        )
        n = len(subscription_set)

        self.data["subscription"] = sorted(
            (user, in_ch)
            for user, in_ch in subscription_set
            if in_ch != chat_id
        )
        self.sync(force=len(self.data["subscription"]) != n)


class DataStorage(BaseStorage):
    """Process data in local file.
    """

    file_path: str

    def __init__(
        self,
        filepath: str = env_var_line("STATE_DATA_FILE") or "state_data.json"
    ):
        super().__init__()
        self.file_path = filepath

    def sync(self, force: bool = False):
        """Sync data.
        """
        if force or (current_datetime() - DUMP_UPDATE_TIME > self.last_update):
            prev_data = curr_data = None
            try:
                with open(self.file_path) as in_file:
                    prev_data = json.loads(in_file.read())
            except Exception as err:
                self.logger.warning(f"File read '{self.file_path}': {err}")

            if isinstance(prev_data, dict):
                prev_users = prev_data.get("users") or []
                prev_values = prev_data.get("values") or {}
                prev_values.update(self.data["values"])
                self.data["values"] = prev_values
                if prev_users:
                    prev_users = set(prev_users)
                    prev_users.update(self.data.get("users") or [])
                    self.data["users"] = sorted(prev_users)

            self.last_update = datetime.now()
            curr_state = self.data["state"] = uuid.uuid4().hex
            try:
                with open(self.file_path, "w") as out_file:
                    out_file.write(json.dumps(self.data))
            except Exception as err:
                self.logger.error(f"File write '{self.file_path}': {err}")
                return
            # reread
            try:
                with open(self.file_path) as in_file:
                    curr_data = json.loads(in_file.read())
            except Exception as err:
                self.logger.warning(f"File read '{self.file_path}': {err}")
            else:
                if isinstance(curr_data, dict):
                    state = curr_data.get("state")
                    if state and state != curr_state:
                        self.logger.warning(
                            f"State conflict {stat} and {curr_state}"
                        )
                        self.sync()
