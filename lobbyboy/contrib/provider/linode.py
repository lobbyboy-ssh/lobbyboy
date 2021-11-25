import os
import logging
from pathlib import Path
from typing import List, Tuple

from linode_api4 import LinodeClient, Region, Type, Image, Instance
from paramiko.channel import Channel

from lobbyboy.provider import BaseProvider
from lobbyboy.utils import send_to_channel, port_is_open, choose_option
from lobbyboy.config import LBConfigProvider, LBServerMeta

logger = logging.getLogger(__name__)
ENV_TOKEN_NAME = "LINODE_TOKEN"


class LinodeProvider(BaseProvider):
    def __init__(self, name: str, config: LBConfigProvider, workspace: Path):
        super().__init__(name, config, workspace)
        self.__token = os.getenv(ENV_TOKEN_NAME) or config.api_token

    @staticmethod
    def linode_is_up(node: Instance) -> bool:
        try:
            is_success = node.stats == "running"
            logger.debug(f"linode(name: {node.label}) status: {node.stats}.")
            return is_success
        except Exception as e:
            logger.error(f"check linode {node.label} status failed: {str(e)}")
            return False

    def create_server(self, channel: Channel) -> LBServerMeta:
        region_id, type_id, image_id = self._ask_user_customize_server(channel)
        server_name = self.generate_default_server_name()
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)

        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        # confirm ssh key pairs
        ssh_keys = self.collection_ssh_keys(save_path=server_workspace)
        logger.info(f"prepare ssh key pairs for server {server_name} done.")

        logger.info(
            f"going to create a new node in linode... "
            f"server name={server_name}, region={region_id}, image={image_id}, type={type_id}"
        )

        send_to_channel(channel, "Waiting for server to created...")
        li = LinodeClient(token=self.__token)
        res = li.linode.instance_create(type_id, region_id, image_id, label=server_name, authorized_keys=ssh_keys)
        linode_instance: Instance = res if isinstance(res, Instance) else res[0]
        self.time_process_action(channel, self.linode_is_up, interval=5, node=linode_instance)
        return self.prepare_after_server_created(channel, linode_instance, server_workspace, server_name)

    def prepare_after_server_created(
        self, channel: Channel, instance: Instance, workspace: Path, server_name: str
    ) -> LBServerMeta:
        # todo: support use startup script after server created
        send_to_channel(channel, f"New server {server_name} (IP: {instance.ipv4}) created!")

        # save server info to local first
        # TODO `_serialize` information le less
        instance_info = instance._serialize()  # noqa
        instance_info["id"] = instance.id
        self.save_raw_server(instance_info, workspace)  # noqa

        # wait for server to startup(check port is alive or not)
        send_to_channel(channel, "Waiting for server to boot...")
        self.time_process_action(channel, port_is_open, ip=instance.ipv4[0])
        send_to_channel(channel, f"Server {server_name} has boot successfully!")

        return LBServerMeta(
            provider_name=self.name,
            server_name=server_name,
            workspace=workspace,
            server_host=instance.ipv4[0],
        )

    def _ask_user_customize_server(self, channel: Channel) -> Tuple[str, str, str]:
        manually_create_choice = "Manually choose a new linode to create.."
        options = [manually_create_choice, *self.provider_config.favorite_instance_types]
        user_selected_idx = choose_option(channel, options, ask_prompt="Please choose new linode to create: ")
        user_selected = options[user_selected_idx]
        logger.info(f"choose linode, user selected: {user_selected_idx}: {user_selected}")
        if user_selected_idx == 0:
            return self._manually_create_new_node(channel)
        region_id, type_id, image_id = user_selected.split(":")
        return region_id, type_id, image_id

    def _manually_create_new_node(self, channel) -> Tuple[str, str, str]:
        linode = LinodeClient(token=self.__token)

        send_to_channel(channel, "Fetching metadata from linode...")
        regions: List[Region] = [i for i in linode.regions()]
        types: List[Type] = [i for i in linode.linode.types()]
        images: List[Image] = [i for i in linode.images()]

        region_slugs = [f"{r.id:15} - {r.country:3} | status: {r.status:5}" for r in regions]
        selected_region_idx = choose_option(channel, region_slugs, ask_prompt="Please choose region: ")
        selected_region: Region = regions[selected_region_idx]

        size_slugs = [
            (
                f"{t.id:18} | Disk: {t.disk:10} | Mem: {t.memory:10} | Label: {t.label:35} | "
                f"Price($): hourly: {t.price.hourly:8}, monthly: {t.price.monthly:8}"
            )
            for t in types
        ]
        selected_type_idx = choose_option(channel, size_slugs, ask_prompt="Please choose linode size: ")
        selected_type: Type = types[selected_type_idx]

        size_images = [
            (
                f"{i.id:30} | size: {round(i.size/1024, 2):5}G | created: {str(i.created)} | "
                f"Deprecated: {i.deprecated:3} | Provider: {i.created_by:8}"
            )
            for i in images
        ]
        selected_image_idx = choose_option(channel, size_images, ask_prompt="Please choose linode image: ")
        selected_size_images: Image = images[selected_image_idx]

        return selected_region.id, selected_type.id, selected_size_images.id

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        logger.info(f"try to destroy {meta.server_name} under workspace {meta.workspace}...")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name}...")
        data = self.load_raw_server(meta.workspace)

        instance: Instance = LinodeClient(token=self.__token).linode.instances(Instance.id == data["id"]).first()
        logger.info(f"get object from linode: {instance}")
        result = instance.delete()
        logger.info(f"destroy linode, result: {result}")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name} done.")
        return result
