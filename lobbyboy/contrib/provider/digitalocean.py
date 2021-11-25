import os
import logging
from pathlib import Path
from typing import List, Tuple

from digitalocean import Droplet, Region, Size, Image, Manager
from paramiko.channel import Channel

from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel, port_is_open, choose_option, lb_dict_factory
from lobbyboy.config import LBConfigProvider, LBServerMeta

logger = logging.getLogger(__name__)
ENV_TOKEN_NAME = "DIGITALOCEAN_TOKEN"


class DigitalOceanProvider(BaseProvider):
    def __init__(self, name: str, config: LBConfigProvider, workspace: Path):
        super().__init__(name, config, workspace)
        self.__token = os.getenv(ENV_TOKEN_NAME) or config.api_token

    @staticmethod
    def droplet_is_up(uninitialized_droplet: Droplet) -> bool:
        actions = uninitialized_droplet.get_actions()
        logger.info(f"create server actions: {actions}")
        for action in actions:
            action.load()
            # Once it shows "completed", droplet is up and running
            if action.status == "completed":
                logger.debug(f"create droplet(name: {uninitialized_droplet.name}) result: {action.status}.")
                return True
        return False

    def create_server(self, channel: Channel) -> LBServerMeta:
        region, size, image = self._ask_user_customize_server(channel)
        server_name = self.generate_default_server_name()
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)

        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        # confirm ssh key pairs
        ssh_keys = self.collection_ssh_keys(save_path=server_workspace)
        logger.info(f"prepare ssh key pairs for server {server_name} done.")

        logger.info(
            f"going to create a new droplet in digitalocean... "
            f"server name={server_name}, region={region}, image={image}, size_slug={size}"
        )
        droplet: Droplet = Droplet(
            token=self.__token,
            name=server_name,
            region=region,
            image=image,
            size_slug=size,
            ssh_keys=ssh_keys,
        )
        send_to_channel(channel, "Waiting for server to created...")
        droplet.create()
        self.time_process_action(channel, self.droplet_is_up, uninitialized_droplet=droplet)
        return self.prepare_after_server_created(channel, droplet, server_workspace, server_name)

    def prepare_after_server_created(
        self, channel: Channel, droplet: Droplet, workspace: Path, server_name: str
    ) -> LBServerMeta:
        # todo: support use startup script after server created
        # load full information from digitalocean before use this droplet to other operations
        droplet.load()
        send_to_channel(channel, f"New server {server_name} (IP: {droplet.ip_address}) created!")

        # save server info to local first
        droplet_meta = lb_dict_factory(
            droplet.__dict__, ignore_fields=["tokens"], ignore_rules=lambda x: x.startswith("_")
        )
        self.save_raw_server(droplet_meta, workspace)

        # wait for server to startup(check port is alive or not)
        send_to_channel(channel, "Waiting for server to boot...")
        self.time_process_action(channel, port_is_open, ip=droplet.ip_address)
        send_to_channel(channel, f"Server {server_name} has boot successfully!")

        return LBServerMeta(
            provider_name=self.name,
            server_name=server_name,
            workspace=workspace,
            server_host=droplet.ip_address,
        )

    def _ask_user_customize_server(self, channel: Channel) -> Tuple[str, str, str]:
        manually_create_choice = "Manually choose a new droplet to create.."
        options = [manually_create_choice, *self.provider_config.favorite_instance_types]
        user_selected_idx = choose_option(channel, options, ask_prompt="Please choose new droplet to create: ")
        user_selected = options[user_selected_idx]
        logger.info(f"choose droplet, user selected: {user_selected_idx}: {user_selected}")
        if user_selected_idx == 0:
            return self._manually_create_new_droplet(channel)
        region, size, image = user_selected.split(":")
        return region, size, image

    def _manually_create_new_droplet(self, channel) -> Tuple[str, str, str]:
        do_manager = Manager(token=self.__token)

        send_to_channel(channel, "Fetching metadata from digitalocean...")
        regions: List[Region] = do_manager.get_all_regions()
        sizes: List[Size] = do_manager.get_all_sizes()
        _images: List[Image] = do_manager.get_all_images()
        # backup image is not usable
        images = [i for i in _images if i.slug is not None]

        region_slugs = [f"{r.name} ({r.slug})" for r in regions]
        selected_region_idx = choose_option(channel, region_slugs, ask_prompt="Please choose region: ")
        selected_region: Region = regions[selected_region_idx]

        size_slugs = [s.slug for s in sizes]
        selected_size_idx = choose_option(channel, size_slugs, ask_prompt="Please choose droplet size: ")
        selected_size: Size = sizes[selected_size_idx]

        size_images = [f"{i.distribution}: {i.name} ({i.slug})" for i in images]
        selected_image_idx = choose_option(channel, size_images, ask_prompt="Please choose droplet image: ")
        selected_size_images: Image = images[selected_image_idx]

        return selected_region.slug, selected_size.slug, selected_size_images.slug

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        logger.info(f"try to destroy {meta.server_name} under workspace {meta.workspace}...")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name}...")
        data = self.load_raw_server(meta.workspace)

        droplet = Droplet.get_object(api_token=self.__token, droplet_id=data["id"])
        logger.info(f"get object from digitalocean: {droplet}")
        result = droplet.destroy()
        logger.info(f"destroy droplet, result: {result}")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name} done.")
        return result
