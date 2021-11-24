import logging
import subprocess
from pathlib import Path

from paramiko import Channel

from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.exceptions import VagrantProviderException, NoAvailableNameException
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel

logger = logging.getLogger(__name__)


class VagrantProvider(BaseProvider):
    def __init__(self, name: str, config: LBConfigProvider, workspace: Path):
        super().__init__(name, config, workspace)

    def generate_server_name(self):
        vm_name = None
        for idx in range(1, 99):
            vm_name = f"{self.provider_config.server_name_prefix}-{idx}"
            server_workspace = self.workspace.joinpath(vm_name)
            if not server_workspace.exists():
                return vm_name
        raise NoAvailableNameException(f"{self.name}'s server {vm_name}[a-z] already exist!")

    def create_server(self, channel: Channel) -> LBServerMeta:
        server_name = self.generate_server_name()
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)

        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        with open(server_workspace.joinpath("Vagrantfile"), "w+") as f:
            f.write(self.provider_config.vagrantfile.format(boxname=server_workspace))

        self.time_process_action(channel, self._run_vagrant, command_exec=["vagrant", "up"], cwd=str(server_workspace))
        send_to_channel(channel, f"New server {server_name} created!")

        send_to_channel(channel, "Waiting for server to boot...")
        self.time_process_action(
            channel,
            self._run_vagrant,
            command_exec=["vagrant", "ssh-config", server_name],
            cwd=str(server_workspace),
            stdout=open(server_workspace / "ssh_config", "wb+"),
        )
        send_to_channel(channel, f"Server {server_name} has boot successfully!")

        return LBServerMeta(
            provider_name=self.name,
            server_name=server_name,
            workspace=server_workspace,
            server_host="127.0.0.1",
        )

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        vid = self._get_vagrant_machine_id(meta.server_name)
        return_code, _, _ = self._run_vagrant(["vagrant", "destroy", "-f", vid])
        success = return_code == 0
        if not success:
            raise VagrantProviderException("Error when destroy {}".format(vid))
        return success

    @staticmethod
    def _run_vagrant(command_exec: list, cwd=None, stdout=None):
        cmd = " ".join(command_exec)
        logger.info(f"start to run command: {cmd}")
        capture_output = stdout is None
        vagrant_process = subprocess.run(command_exec, cwd=cwd, capture_output=capture_output, stdout=stdout)
        if vagrant_process.returncode == 0:
            logger.info(
                f"vagrant_command SUCCESS, command={cmd} "
                f"stdout={vagrant_process.stdout}, stderr={vagrant_process.stderr}"
            )
            return vagrant_process.returncode, vagrant_process.stdout, vagrant_process.stderr
        logger.error(
            f"vagrant_command FAILED! command={cmd} return_code: {vagrant_process.returncode}, "
            f"stdout: {vagrant_process.stdout}, stdout: {vagrant_process.stderr}"
        )
        raise Exception

    def _get_vagrant_machine_id(self, server_name):
        _, stdout, _ = self._run_vagrant(["vagrant", "global-status"])
        for line in stdout.decode().split("\n"):
            if server_name in line:
                v_server_id = line.split(" ")[0]
                logger.debug(f"Find server_id={v_server_id} by server name {server_name}")
                return v_server_id
        raise VagrantProviderException(f"{server_name} not found in Vagrant!")
