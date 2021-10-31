import os
import json
import logging
import datetime
import paramiko
import digitalocean as do
import threading
import time
import socket


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
        region, size, image = self._ask_user_custmize_server(chan)
        logger.info(
            (
                "going to create a new droplet in digitalocean... name={}, "
                "region={}, image={}, size_slug={}"
            ).format(server_name, region, image, size)
        )
        droplet = do.Droplet(
            token=os.getenv("DIGITALOCEAN_TOKEN"),
            name=server_name,
            region=region,
            image=image,
            size_slug=size,
            ssh_keys=ssh_keys,
        )
        event = threading.Event()
        self.send_timepass(chan, event)
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
        event.set()
        server_info_path = str(server_data / "server.json")
        self._dump_info(droplet, server_info_path)
        chan.send(
            "New server {}({}) created!\r\n".format(
                server_name, droplet.ip_address
            ).encode()
        )
        # wait for server to start up...
        chan.send("Waiting server to boot...\r\n".encode())
        self.block_test_server_connectable(droplet.ip_address, 22)
        return server_name, droplet.ip_address

    def block_test_server_connectable(self, ip, port):

        location = (ip, int(port))
        result = 1
        count = 1
        while result != 0:
            a_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            a_socket.settimeout(2)
            result = a_socket.connect_ex(location)
            a_socket.close()
            logger.debug("{} check, reuslt is {}".format(count, result))
            time.sleep(1)
            count += 1

    def _ask_user_custmize_server(self, chan):
        manually_create_choice = "Manually choose a new droplet to create..."
        favorites = [manually_create_choice] + self.provider_config["favorite_droplets"]
        choosed, _ = self.choose_option(
            "Please choose new droplet to create: ", favorites, chan
        )
        logger.info("choose droplet, user choosed: {}".format(choosed))
        if choosed == manually_create_choice:
            return self._manually_create_new_droplet(chan)
        region, size, image = choosed.split(":")
        return region, size, image

    def _manually_create_new_droplet(self, chan):
        do_manager = do.Manager(token=self.token)

        chan.send("Fetching metadata from digitalocean...\r\n".encode())
        regions = do_manager.get_all_regions()
        sizes = do_manager.get_all_sizes()
        images = do_manager.get_all_images()
        # backup image is not usable
        images = [image for image in images if image.slug is not None]

        region_slugs = ["{} ({})".format(r.name, r.slug) for r in regions]
        _, choosed_region_index = self.choose_option(
            "Please choose region: ", region_slugs, chan
        )
        choosed_region = regions[choosed_region_index].slug

        size_slugs = [s.slug for s in sizes]
        choosed_size, _ = self.choose_option(
            "Please choose droplet size: ", size_slugs, chan
        )

        size_slugs = [
            "{}: {} ({})".format(i.distribution, i.name, i.slug) for i in images
        ]
        _, choosed_index = self.choose_option(
            "Please choose droplet image: ", size_slugs, chan
        )

        return choosed_region, choosed_size, images[choosed_index].slug

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
        for suffix in "abcdefg":
            vm_data = self.data_path / (server_name + suffix)
            if not vm_data.exists():
                os.mkdir(str(vm_data))
                return server_name + suffix
        raise NoAvailableNameException("Server {} already exist!".format(server_name))

    def destroy_server(self, server_id, server_ip, channel):
        logger.info("try to destroy {} {}...".format(server_id, server_ip))
        with open(self.data_path / server_id / "server.json", "r") as sfile:
            data = json.load(sfile)
        do_id = data["id"]
        droplet = do.Droplet.get_object(
            api_token=self.token,
            droplet_id=do_id,
        )
        logger.info("get object from digitalocean: {}".format(droplet))
        result = droplet.destroy()
        logger.info("destroy droplet, result: {}".format(result))

    def ssh_server_command(self, server_id, server_ip):
        keypath = str(self.data_path / server_id / "id_rsa")
        command = [
            "ssh",
            "-i",
            keypath,
            "-o",
            "StrictHostKeyChecking=no",
            "root@{}".format(server_ip),
        ]
        logger.info("returning ssh command: {}".format(command))
        return command
