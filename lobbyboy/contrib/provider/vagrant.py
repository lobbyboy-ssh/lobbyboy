import logging
import subprocess
from pathlib import Path
from typing import List, Optional

from paramiko import Channel

from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.exceptions import VagrantProviderException, NoAvailableNameException
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel

logger = logging.getLogger(__name__)


class VagrantProvider(BaseProvider):
    def __init__(self, name: str, config: LBConfigProvider, workspace: Path):
        super().__init__(name, config, workspace)
        self._tmp_ssh_config_file: Optional[Path] = None

    def generate_server_name(self):
        vm_name = None
        for idx in range(1, 99):
            vm_name = str(idx)
            if self.provider_config.server_name_prefix:
                vm_name = f"{self.provider_config.server_name_prefix}-{vm_name}"
            server_workspace = self.workspace.joinpath(vm_name)
            if not server_workspace.exists():
                return vm_name
        raise NoAvailableNameException(f"{self.name}'s server {vm_name}[a-z] already exist!")

    def create_server(self, channel: Channel) -> LBServerMeta:
        server_name = self.generate_server_name()
        logger.info(f"got server name for vagrant: {server_name}.")
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)

        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        with open(server_workspace.joinpath("Vagrantfile"), "w+") as f:
            f.write(self.provider_config.vagrantfile.format(boxname=server_name))

        vagrant_up_process = VagrantProvider._popen_vagrant(["vagrant", "up"], cwd=str(server_workspace))
        logger.debug("vagrant up process %s", vagrant_up_process.pid)

        def vagrant_up():
            return vagrant_up_process.poll() == 0

        self.time_process_action(channel, vagrant_up)
        send_to_channel(channel, f"New server {server_name} created!")

        # export the ssh_config to file
        self._tmp_ssh_config_file = server_workspace.joinpath("ssh_config")
        VagrantProvider._run_vagrant(
            command_exec=["vagrant", "ssh-config", server_name],
            cwd=str(server_workspace),
            stdout=open(self._tmp_ssh_config_file, "wb+"),
        )

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

    def ssh_server_command(self, meta: LBServerMeta, pri_key_path: Path = None) -> List[str]:
        command = [
            "ssh",
            "-F",
            self._tmp_ssh_config_file,
            *meta.ssh_extra_args,
            meta.server_name,
        ]
        logger.info(f"returning ssh command: {command}")
        return command

    @staticmethod
    def _run_vagrant(command_exec: list, cwd=None, stdout=None):
        p = VagrantProvider._popen_vagrant(command_exec, cwd, stdout)
        p.wait()
        returncode = p.returncode
        stdout = p.stdout
        if stdout is not None:
            stdout = stdout.read().decode()
        stderr = p.stderr
        if stderr is not None:
            stderr = stderr.read().decode()
        if returncode == 0:
            logger.info(f"vagrant_command SUCCESS, command={' '.join(command_exec)} stdout={stdout}, stderr={stderr}")
            return returncode, stdout, stderr
        logger.error(f"vagrant_command SUCCESS, command={' '.join(command_exec)} stdout={stdout}, stderr={stderr}")
        raise Exception

    @staticmethod
    def _popen_vagrant(command_exec: list, cwd=None, stdout=None):
        cmd = " ".join(command_exec)
        logger.info(f"start to run command: {cmd}")
        if stdout is None:
            stdout = subprocess.PIPE
        vagrant_process = subprocess.Popen(command_exec, cwd=cwd, stdout=stdout, stderr=subprocess.PIPE, close_fds=True)
        return vagrant_process

    def _get_vagrant_machine_id(self, server_name):
        _, stdout, _ = self._run_vagrant(["vagrant", "global-status"])
        for line in stdout.decode().split("\n"):
            if server_name in line:
                v_server_id = line.split(" ")[0]
                logger.debug(f"Find server_id={v_server_id} by server name {server_name}")
                return v_server_id
        raise VagrantProviderException(f"{server_name} not found in Vagrant!")
