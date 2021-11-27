import json
import string
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
import logging
import time
from typing import List, Dict, Callable

from paramiko.channel import Channel

from lobbyboy.exceptions import NoAvailableNameException
from lobbyboy.utils import (
    confirm_ssh_key_pair,
    send_to_channel,
    KeyTypeSupport,
)
from lobbyboy.config import LBConfigProvider, LBServerMeta

logger = logging.getLogger(__name__)
SERVER_FILE = "server.json"


class BaseProvider(ABC):
    def __init__(self, provider_name: str, config: LBConfigProvider, workspace: Path):
        self.name: str = provider_name
        self.provider_config: LBConfigProvider = config
        self.workspace: Path = workspace

    def generate_default_server_name(self):
        server_name = datetime.now().strftime("%Y-%m-%d-%H%M")
        if self.provider_config.server_name_prefix:
            server_name = f"{self.provider_config.server_name_prefix}-{server_name}"

        for suffix in ["", *string.ascii_lowercase]:
            _server_name = f"{server_name}{suffix}"
            server_workspace = self.workspace.joinpath(_server_name)
            if not server_workspace.exists():
                server_workspace.mkdir(parents=True)
                return _server_name
        raise NoAvailableNameException(f"{self.name}'s server {server_name}[a-z] already exist!")

    def get_server_workspace(self, server_name: str) -> Path:
        return self.workspace.joinpath(server_name)

    @staticmethod
    def time_process_action(
        channel: Channel, action: Callable, max_check: int = 20, interval: int = 3, **action_kws
    ) -> bool:
        """
        This is a helper function, it block until ``action`` is done (when the
        ``action`` returns True, consider it as "done"). Before the action
        being done, the check will be executed(``action`` being called) every
        ``internal` seconds, until ``max_check`` limit exceed.

        For every check, LobbyBoy ssh server will send a "." to ssh user to
        incident that it starts a new turn or check. When the ``action`` final
        return ``True``, LobbyBoy will show the total time cost to user.

        Args:
           channel: paramiko channel
           action: execute with time process, need return bool
           max_check: max check times
           interval: check interval in seconds

        Returns:
            bool: bool result before end of check time
        """
        action_name = " ".join(action.__name__.split("_"))
        logger.debug("watch a new action, action_name: %s", action_name)
        send_to_channel(channel, f"Check {action_name}", suffix="")
        start_at = time.time()
        try_times = 1
        while try_times <= max_check:
            send_to_channel(channel, ".", suffix="")
            res = action(**action_kws)
            if res:
                send_to_channel(channel, f"OK({round(time.time() - start_at, 2)}s).")
                return res
            time.sleep(interval)
            try_times += 1
        send_to_channel(
            channel,
            "\n I have checked {} times for action {}, still not finished, give up...".format(max_check, action_name),
        )
        return False

    @staticmethod
    def save_raw_server(server_obj: Dict, server_workspace: Path) -> Path:
        _path = server_workspace.joinpath(SERVER_FILE)
        with open(_path, "w+") as f:
            logger.debug(f"write new server data to {_path}")
            json.dump(server_obj, f)
        return _path

    @staticmethod
    def load_raw_server(server_workspace: Path):
        _path = server_workspace.joinpath(SERVER_FILE)
        with open(_path, "r+") as f:
            logger.debug(f"load server data from {_path}")
            return json.load(f)

    @abstractmethod
    def create_server(self, channel: Channel) -> LBServerMeta:
        """
        Args:
            channel: paramiko channel

        Returns:
            LBServerMeta: server meta info
        """
        ...

    @abstractmethod
    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        """
        Args:
            meta: LBServerMeta, we use this to locate one server then destroy it.
            channel: Note that the channel can be None.
                     If called from server_killer, channel will be None.
                     if called when user logout from server, channel is active.

        Returns:
            bool: True if destroy successfully, False if not.
        """
        ...

    def collection_ssh_keys(self, generate: bool = True, save_path: Path = None) -> List[str]:
        ssh_keys = self.provider_config.extra_ssh_keys[::] or []
        if generate:
            _, pub_key = confirm_ssh_key_pair(save_path=save_path or self.workspace)
            ssh_keys.append(pub_key)
        return ssh_keys

    def default_private_key_path(self, workspace: Path = None, key_type: KeyTypeSupport = KeyTypeSupport.RSA) -> Path:
        workspace = workspace or self.workspace
        return workspace.joinpath(f".ssh/id_{key_type.key.lower()}")

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        """
        Args:
           meta: LBServerMeta
           pri_key_path: path to private key

        Returns:
            str: ssh command to connect to provider's server.
        """
        _pri_key_path = pri_key_path or self.default_private_key_path(meta.workspace)
        command = [
            "ssh",
            "-i",
            str(_pri_key_path),
            "-o",
            "StrictHostKeyChecking=no",
            "-p",
            str(meta.server_port),
            "-l",
            meta.server_user,
            *meta.ssh_extra_args,
            meta.server_host,
        ]
        logger.info(f"returning ssh command: {command}")
        return command

    def get_bill(self):
        ...
