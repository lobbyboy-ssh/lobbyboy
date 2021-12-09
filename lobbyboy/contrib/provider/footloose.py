import logging
from pathlib import Path
from dataclasses import dataclass
import subprocess
from typing import List

from paramiko import Channel

from lobbyboy.config import LBServerMeta, LBConfigProvider
from lobbyboy.exceptions import ProviderException
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel


logger = logging.getLogger(__name__)


class FootlooseException(ProviderException):
    pass


@dataclass
class FootlooseConfig(LBConfigProvider):
    footloose_config: str = ""


class FootlooseProvider(BaseProvider):
    config = FootlooseConfig

    # TODO add to pre hook
    def check_footloose_executable(self):
        process = subprocess.run(["footloose", "-h"])
        if process.returncode != 0:
            raise FootlooseException(
                (
                    "footloose executable is not exist! "
                    "Please install footloose via "
                    "`GO111MODULE=on go get github.com/weaveworks/footloose`"
                )
            )
        return True

    def create_server(self, channel: Channel) -> LBServerMeta:
        server_name = self.generate_default_server_name()
        logger.info("footloose generated server_name: %s", server_name)
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)
        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        with open(server_workspace.joinpath("footloose.yaml"), "w+") as f:
            f.write(self.provider_config.footloose_config.format(server_name=server_name))

        footloose_create = subprocess.Popen(["footloose", "create"], cwd=str(server_workspace))
        logger.debug("footloose create process: %s", footloose_create.pid)

        def footloose_create_done():
            return footloose_create.poll() is not None

        self.time_process_action(channel, footloose_create_done)
        if footloose_create.returncode != 0:
            raise FootlooseException("footloose create failed!")
        return LBServerMeta(
            provider_name=self.name, server_name=server_name, workspace=server_workspace, server_host="127.0.0.1"
        )

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        command = ["cd {} && footloose ssh root@{}".format(meta.workspace, meta.server_name + "0")]

        logger.debug("get ssh to server command for footloose: %s", command)
        return command

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        process = subprocess.run(
            ["footloose", "delete", "-c", meta.workspace.joinpath("footloose.yaml")], capture_output=True
        )
        if process.returncode != 0:
            logger.error(
                "fail to delete footloose server %s, returncode: %s, stdout: %s, stderr: %s",
                meta,
                process.returncode,
                process.stdout,
                process.stderr,
            )
            return False
        return True
