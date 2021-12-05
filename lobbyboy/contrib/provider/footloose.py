import logging
from pathlib import Path
from lobbyboy.config import LBServerMeta
from lobbyboy.exceptions import ProviderException
import subprocess
from lobbyboy.provider import BaseProvider
from paramiko import Channel
from typing import List, Optional
from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.utils import send_to_channel


logger = logging.getLogger(__name__)


class FootlooseException(ProviderException):
    pass


class FootlooseProvider(BaseProvider):
    def check_footloose_executable(self):
        process = subprocess.run(["footloose", "-h"])
        if process.returncode != 0:
            raise FootlooseException(
                "footloose executable is not exist! Please install footloose via `GO111MODULE=on go get github.com/weaveworks/footloose`"
            )
        return True

    def create_server(self, channel: Channel) -> LBServerMeta:
        self.check_footloose_executable()
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
            return footloose_create.poll() == 0

        self.time_process_action(channel, footloose_create_done)
        return LBServerMeta(
            provider_name=self.name, server_name=server_name, workspace=server_workspace, server_host="127.0.0.1"
        )

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        command = ["footloose", "ssh", "-c", meta.workspace.joinpath("footloose.yaml"), "root@" + meta.server_name]
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