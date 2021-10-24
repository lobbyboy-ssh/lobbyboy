import logging
import os
import subprocess
import threading
from lobbyboy.provider import BaseProvider


logger = logging.getLogger(__name__)


class VagrantProvider(BaseProvider):
    """
    This provider will provision new VM via local vagrant daemon.
    It won't create a real VPS, this is just a provider implementation ref.
    """

    def get_unused_vm_name(self):
        for index in range(1, 99):
            vm_name = "lobbyboy-{}".format(index)
            if not (self.data_path / vm_name).exists():
                return vm_name
        raise Exception("Can not create more VMs!")

    def new_server(self, chan):
        vm_name = self.get_unused_vm_name()
        vm_path = self.data_path / vm_name
        os.mkdir(str(vm_path))
        with open(str(vm_path / "Vagrantfile"), "w+") as vfile:
            file_content = self.provider_config["vagrantfile"].format(boxname=vm_name)
            vfile.write(file_content)

        over_event = threading.Event()
        self.send_timepass(chan, over_event)

        vagrant_process = subprocess.run(
            ["vagrant", "up"], cwd=str(vm_path), capture_output=True
        )
        over_event.set()
        if vagrant_process.returncode == 0:
            logger.info(
                "new server created! stdout={}, stderr={}".format(
                    vagrant_process.stdout, vagrant_process.stderr
                )
            )
            chan.send("New server {} created!\r\n".format(vm_name).encode())
            return vm_name, "127.0.0.1"
        logger.error(
            "error when vagrant up... returncode: {}, stdout: {}, stdout: {}".format(
                vagrant_process.returncode,
                vagrant_process.stdout,
                vagrant_process.stderr,
            )
        )
        raise Exception

    def ssh_server_command(self, server_id, server_ip):
        vid = self._get_vagrant_machine_id(server_id)
        return ["vagrant", "ssh", vid]

    def destroy_server(self, server_id, server_ip, channel):
        vid = self._get_vagrant_machine_id(server_id)
        vagrant_process = subprocess.run(
            ["vagrant", "destroy", "-f", vid], capture_output=True
        )
        if vagrant_process.returncode == 0:
            logger.info("destroy server {} success.".format(vid))
            return
        logger.info(
            "error when destroy {}, returncode={}, stdout={}, stderr={}".format(
                vid,
                vagrant_process.returncode,
                vagrant_process.stdout.decode(),
                vagrant_process.stderr.decode(),
            )
        )
        raise Exception("Error when destroy {}".format(vid))

    def _get_vagrant_machine_id(self, server_id):
        vagrant_process = subprocess.run(
            ["vagrant", "global-status"], capture_output=True
        )
        stdout = vagrant_process.stdout.decode()
        for line in stdout.split("\n"):
            if server_id in line:
                v_server_id = line.split(" ")[0]
                logger.debug(
                    "Find server_id={} by server name {}".format(v_server_id, server_id)
                )
                return v_server_id
