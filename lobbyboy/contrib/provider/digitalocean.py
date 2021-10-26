import os
import json
import logging
import datetime
import paramiko
import digitalocean
import threading
import time


from lobbyboy.provider import BaseProvider
from lobbyboy.exceptions import ProviderException


DEFAULT_RSA_BITS = 3072
logger = logging.getLogger(__name__)


class NoAvailableNameException(ProviderException):
    pass


class DigitalOceanProvider(BaseProvider):
    def __init__(self, provider_name, config, provider_config, data_path):
        super().__init__(provider_name, config, provider_config, data_path)
        token = os.getenv("DIGITALOCEAN_TOKEN")
        if token:
            self.token = token
        else:
            self.token = provider_config["private_key"]

    def new_server(self, chan):
        server_name = self._generate_name()
        server_data = self.data_path / server_name
        key = self._generate_private_key(server_data)
        pubkey = "{} {}".format(key.get_name(), key.get_base64())
        ssh_keys = self.provider_config["extra_ssh_keys"]
        ssh_keys.append(pubkey)
        event = threading.Event()
        self.send_timepass(chan, event)
        droplet = digitalocean.Droplet(
            token=os.getenv("DIGITALOCEAN_TOKEN"),
            name=server_name,
            region="sgp1",  # New York 2
            image="ubuntu-20-04-x64",  # Ubuntu 20.04 x64
            size_slug="s-1vcpu-1gb",  # 1GB RAM, 1 vCPU
            ssh_keys=ssh_keys,
        )
        droplet.create()
        logger.info("create server data dir: {}".format(server_data))
        actions = droplet.get_actions()
        logger.info("create server actions: {}".format(actions))
        action1 = actions[0]
        check = 0
        while 1:
            if check <= 2:
                time.sleep(5)
            else:
                time.sleep(1)

            logger.debug("{} time check for action: {}".format(check, action1))
            check += 1
            action1.load()
            logger.debug("check result: {}".format(action1))
            # Once it shows "completed", droplet is up and running
            if action1.status == "completed":
                break

        droplet.load()
        ssh_command = self.ssh_server_command(server_name, droplet.ip_address)
        logger.info(ssh_command)
        # wait for server to start up...
        time.sleep(15)
        event.set()
        server_info_path = str(server_data / "server.json")
        self._dump_info(droplet, server_info_path)
        chan.send(
            "New server {}({}) created!\r\n".format(
                server_name, droplet.ip_address
            ).encode()
        )
        return server_name, droplet.ip_address

    def _dump_info(self, droplet, path):
        data = {
            "id": droplet.id,
            "name": droplet.name,
            "memory": droplet.memory,
            "vcpus": droplet.vcpus,
            "disk": droplet.disk,
            "region": droplet.region,
            "image": droplet.image,
            "size_slug": droplet.size_slug,
            "locked": droplet.locked,
            "created_at": droplet.created_at,
            "status": droplet.status,
            "networks": droplet.networks,
            "kernel": droplet.kernel,
            "backup_ids": droplet.backup_ids,
            "snapshot_ids": droplet.snapshot_ids,
            "action_ids": droplet.action_ids,
            "features": droplet.features,
            "ip_address": droplet.ip_address,
            "private_ip_address": droplet.private_ip_address,
            "ip_v6_address": droplet.ip_v6_address,
            "ssh_keys": droplet.ssh_keys,
            "backups": droplet.backups,
            "ipv6": droplet.ipv6,
            "private_networking": droplet.private_networking,
            "user_data": droplet.user_data,
            "volumes": droplet.volumes,
            "tags": droplet.tags,
            "monitoring": droplet.monitoring,
            "vpc_uuid": droplet.vpc_uuid,
        }
        with open(path, "w+") as serverf:
            json.dump(data, serverf)
            logger.debug("server data write to {}".format(serverf))

    def _generate_private_key(self, path):
        path = path / "id_rsa"
        rsa_key = paramiko.RSAKey.generate(DEFAULT_RSA_BITS)
        rsa_key.write_private_key_file(str(path))
        return rsa_key

    def _generate_name(self):
        datestr = datetime.datetime.now().strftime("%Y-%m-%d-%H%M")
        server_name = "lobbyboy-{}".format(datestr)
        vm_data = self.data_path / server_name
        if not vm_data.exists():
            os.mkdir(str(vm_data))
            return server_name
        raise NoAvailableNameException("Server {} already exist!".format(server_name))

    def destroy_server(self, server_id, server_ip, channel):
        logger.info("try to destroy {} {}...".format(server_id, server_ip))
        with open(self.data_path / server_id / "server.json", "r") as sfile:
            data = json.load(sfile)
        do_id = data['id']
        droplet = digitalocean.Droplet.get_object(
            api_token=self.token,
            droplet_id=do_id,
        )
        logger.info("get object from digitalocean: {}".format(droplet))
        result = droplet.destroy()
        logger.info("destroy droplet, result: {}".format(result))


    def ssh_server_command(self, server_id, server_ip):
        keypath = str(self.data_path / server_id / "id_rsa")
        command = ["ssh", "-i", keypath, "-o",  "StrictHostKeyChecking=no", "root@{}".format(server_ip)]
        logger.info("returning ssh command: {}".format(command))
        return command
