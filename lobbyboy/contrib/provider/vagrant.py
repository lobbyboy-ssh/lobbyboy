import logging
import os
import subprocess
import threading
from lobbyboy.provider import BaseProvider
from lobbyboy.exceptions import ProviderException


logger = logging.getLogger(__name__)


class VagrantProviderException(ProviderException):
    pass


class VagrantProvider(BaseProvider):
    """
    This provider will provision new VM via local vagrant daemon.
    It won't create a real VPS, this is just a provider implementation ref.
    """

    def get_unused_vm_name(self):
        for index in range(1, 10000):
            vm_name = "lobbyboy-{}".format(index)
            if not (self.data_path / vm_name).exists():
                return vm_name
        logger.error(
            "vagrant can not found a available vm name, all id from 1 to 9999 are taken, please clean out {}".format(
                self.data_path
            )
        )
        raise Exception(
            "Can not create more VMs! Please clean out {}".format(self.data_path)
        )

    def new_server(self, chan):
        vm_name = self.get_unused_vm_name()
        vm_path = self.data_path / vm_name
        os.mkdir(str(vm_path))
        with open(str(vm_path / "Vagrantfile"), "w+") as vfile:
            file_content = self.provider_config["vagrantfile"].format(boxname=vm_name)
            vfile.write(file_content)

        over_event = threading.Event()
        self.send_timepass(chan, over_event)
        self._run_vagrant(["vagrant", "up"], cwd=str(vm_path))
        ssh_config_file = open(vm_path / "ssh_config", "wb+")
        self._run_vagrant(
            ["vagrant", "ssh-config", vm_name], cwd=str(vm_path), stdout=ssh_config_file
        )
        over_event.set()
        chan.send("New server {} created!\r\n".format(vm_name).encode())
        return vm_name, "127.0.0.1"

    def _run_vagrant(self, command_exec: list, cwd=None, stdout=None):
        logger.info("start to run command: {}".format(" ".join(command_exec)))
        capture_output = stdout is None
        vagrant_process = subprocess.run(
            command_exec, cwd=cwd, capture_output=capture_output, stdout=stdout
        )
        if vagrant_process.returncode == 0:
            logger.info(
                "vagrant_command success, command={} stdout={}, stderr={}".format(
                    " ".join(command_exec),
                    vagrant_process.stdout,
                    vagrant_process.stderr,
                )
            )
            return (
                vagrant_process.returncode,
                vagrant_process.stdout,
                vagrant_process.stderr,
            )
        logger.error(
            "vagrant_command FAILED! command={} returncode: {}, stdout: {}, stdout: {}".format(
                " ".join(command_exec),
                vagrant_process.returncode,
                vagrant_process.stdout,
                vagrant_process.stderr,
            )
        )
        raise Exception

    def ssh_server_command(self, server_id, server_ip):
        vm_path = self.data_path / server_id / "ssh_config"

        return ["ssh", "-F", str(vm_path), server_id]

    def destroy_server(self, server_id, server_ip, channel):
        vid = self._get_vagrant_machine_id(server_id)
        returncode, _, _ = self._run_vagrant(["vagrant", "destroy", "-f", vid])
        if returncode != 0:
            raise VagrantProviderException("Error when destroy {}".format(vid))

    def _get_vagrant_machine_id(self, server_id):
        _, stdout, _ = self._run_vagrant(["vagrant", "global-status"])
        stdout = stdout.decode()
        for line in stdout.split("\n"):
            if server_id in line:
                v_server_id = line.split(" ")[0]
                logger.debug(
                    "Find server_id={} by server name {}".format(v_server_id, server_id)
                )
                return v_server_id
        raise VagrantProviderException("{} not found in Vagrant!".format(server_id))
