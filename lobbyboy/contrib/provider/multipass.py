import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

from paramiko import Channel

from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.exceptions import ProviderException
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel

logger = logging.getLogger(__name__)


class MultipassException(ProviderException):
    pass


@dataclass
class MultipassConfig(LBConfigProvider):
    server_name_prefix: str = "lobbyboy"
    image: str = "release:20.04"
    cpu: int = 1
    mem: str = "1GB"
    disk: str = "5GB"


class MultipassProvider(BaseProvider):
    config = MultipassConfig

    def is_available(self) -> bool:
        if not self.check_command(["multipass", "-h"]):
            print(
                "multipass executable is not exist! " "Please install it via `snap install multipass`", file=sys.stderr
            )
            return False
        return True

    def create_server(self, channel: Channel) -> LBServerMeta:
        server_name = self.generate_default_server_name()
        logger.info("multipass generated server_name: %s", server_name)
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)
        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        multipass_create = subprocess.Popen(
            [
                "multipass",
                "launch",
                self.provider_config.image,
                "--name",
                server_name,
                "--cpus",
                str(self.provider_config.cpu),
                "--mem",
                self.provider_config.mem,
                "--disk",
                self.provider_config.disk,
            ],
            cwd=str(server_workspace),
        )
        logger.debug("multipass create process: %s", multipass_create.pid)

        def multipass_create_done():
            if multipass_create.poll() is not None:
                output = subprocess.check_output(
                    [
                        "multipass",
                        "info",
                        "--format",
                        "json",
                        server_name,
                    ]
                )
                info = json.loads(output)["info"]
                if info[server_name]["state"].lower() == "running":
                    return True
            return False

        self.time_process_action(channel, multipass_create_done)
        if multipass_create.returncode != 0:
            raise MultipassException("multipass create failed!")
        return LBServerMeta(
            provider_name=self.name, server_name=server_name, workspace=server_workspace, server_host="127.0.0.1"
        )

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        command = ["cd {} && multipass shell {}".format(meta.workspace, meta.server_name)]

        logger.debug("get ssh to server command for multipass: %s", command)
        return command

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        process = subprocess.run(["multipass", "delete", "--purge", meta.server_name], capture_output=True)
        if process.returncode != 0:
            logger.error(
                "fail to delete multipass server %s, returncode: %s, stdout: %s, stderr: %s",
                meta,
                process.returncode,
                process.stdout,
                process.stderr,
            )
            return False
        return True
