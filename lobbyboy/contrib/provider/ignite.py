import logging
from pathlib import Path
import subprocess
from typing import List
from dataclasses import dataclass

from paramiko import Channel

from lobbyboy.config import LBServerMeta, LBConfigProvider
from lobbyboy.exceptions import ProviderException
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel


logger = logging.getLogger(__name__)


class IgniteException(ProviderException):
    pass


@dataclass
class IgniteConfig(LBConfigProvider):
    image: str = "weaveworks/ignite-ubuntu"
    cpu: int = 1
    mem: str = "1GB"
    disk: str = "5GB"


class IgniteProvider(BaseProvider):
    config = IgniteConfig

    # TODO add to pre hook
    def check_ignite_executable(self):
        process = subprocess.run(["ignite", "-h"])
        if process.returncode != 0:
            raise IgniteException(
                (
                    "ignite executable is not exist! "
                    "Please install ignite via the instrution on "
                    "https://ignite.readthedocs.io/en/stable/installation/"
                )
            )
        return True

    def create_server(self, channel: Channel) -> LBServerMeta:
        server_name = self.generate_default_server_name()
        logger.info("ignite generated server_name: %s", server_name)
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)
        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        ignite_create = subprocess.Popen(
            [
                "ignite",
                "run",
                self.provider_config.image,
                "--name",
                server_name,
                "--cpus",
                str(self.provider_config.cpu),
                "--memory",
                self.provider_config.mem,
                "--size",
                self.provider_config.disk,
                "--ssh",
            ],
            cwd=str(server_workspace),
        )
        logger.debug("ignite create process: %s", ignite_create.pid)

        def ignite_create_done():
            return ignite_create.poll() is not None

        self.time_process_action(channel, ignite_create_done)
        if ignite_create.returncode != 0:
            raise IgniteException("ignite create failed!")
        return LBServerMeta(
            provider_name=self.name, server_name=server_name, workspace=server_workspace, server_host="127.0.0.1"
        )

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        command = ["cd {} && ignite ssh {}".format(meta.workspace, meta.server_name)]

        logger.debug("get ssh to server command for ignite: %s", command)
        return command

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        process = subprocess.run(["ignite", "rm", "-f", meta.server_name], capture_output=True)
        if process.returncode != 0:
            logger.error(
                "fail to delete ignite server %s, returncode: %s, stdout: %s, stderr: %s",
                meta,
                process.returncode,
                process.stdout,
                process.stderr,
            )
            return False
        return True
