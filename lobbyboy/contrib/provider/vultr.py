import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from paramiko.channel import Channel
from pyvultr import VultrV2
from pyvultr.v2 import OS, Instance, Plan, Region, ReqInstance, SSHKey
from pyvultr.v2.enums import InstanceStatus

from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.provider import BaseProvider
from lobbyboy.utils import choose_option, port_is_open, send_to_channel

logger = logging.getLogger(__name__)
ENV_TOKEN_NAME = "VULTR_TOKEN"  # nosec: false B105(hardcoded_password_string) by bandit


@dataclass
class VultrConfig(LBConfigProvider):
    favorite_instance_types: List[str] = field(default_factory=list)


class VultrProvider(BaseProvider):
    config = VultrConfig

    def __init__(self, name: str, config: LBConfigProvider, workspace: Path):
        super().__init__(name, config, workspace)
        self.__token = os.getenv(ENV_TOKEN_NAME) or config.api_token
        self.client = VultrV2(self.__token)

    def instance_is_up(self, node_id: str) -> bool:
        try:
            node: Instance = self.client.instance.get(node_id)
            is_success = node.status == InstanceStatus.ACTIVE.value
            logger.debug(f"Vultr(name: {node.label}) status: {node.status}.")
            return is_success
        except Exception as e:
            logger.error(f"check vlutr {node_id} status failed: {str(e)}")
            return False

    def create_server(self, channel: Channel) -> LBServerMeta:
        region_id, plan_id, image_id = self._ask_user_customize_server(channel)
        server_name = self.generate_default_server_name()
        server_workspace = self.get_server_workspace(server_name)
        server_workspace.mkdir(exist_ok=True, parents=True)

        logger.info(f"create {self.name} server {server_name} workspace: {server_workspace}.")
        send_to_channel(channel, f"Generate server {server_name} workspace {server_workspace} done.")

        # confirm ssh key pairs
        ssh_keys = self.collection_ssh_keys(save_path=server_workspace)
        logger.info(f"prepare ssh key pairs for server {server_name} done.")

        logger.info(
            f"going to create a new node in vultr... "
            f"server name={server_name}, region={region_id}, image={image_id}, type={plan_id}"
        )

        send_to_channel(channel, "Waiting for server to created...")
        ssh_key_ids = []
        for idx, ssh_key in enumerate(ssh_keys):
            res: SSHKey = self.client.ssh_key.create(f"{server_name}-{idx}", ssh_key)
            ssh_key_ids.append(res.id)
        instance: Instance = self.client.instance.create(
            ReqInstance(
                region=region_id,
                plan=plan_id,
                os_id=int(image_id),
                label=server_name,
                tag=server_name,
                sshkey_id=ssh_key_ids or None,
            )
        )
        self.time_process_action(channel, self.instance_is_up, interval=5, node_id=instance.id)
        return self.prepare_after_server_created(channel, instance, server_workspace, server_name)

    def prepare_after_server_created(
        self, channel: Channel, instance: Instance, workspace: Path, server_name: str
    ) -> LBServerMeta:
        # refresh instance info, in case of some data of instance is missing.
        instance: Instance = self.client.instance.get(instance.id)

        send_to_channel(channel, f"New server {server_name} (IP: {instance.main_ip}) created!")

        # save server info to local first
        self.save_raw_server(instance.to_dict(), workspace)

        # wait for server to startup(check port is alive or not)
        send_to_channel(channel, "Waiting for server to boot...")
        self.time_process_action(channel, port_is_open, ip=instance.main_ip)
        send_to_channel(channel, f"Server {server_name} has boot successfully!")

        return LBServerMeta(
            provider_name=self.name,
            server_name=server_name,
            workspace=workspace,
            server_host=instance.main_ip,
        )

    def _ask_user_customize_server(self, channel: Channel) -> Tuple[str, str, str]:
        manually_create_choice = "Manually choose a new vultr to create.."
        options = [manually_create_choice, *self.provider_config.favorite_instance_types]
        user_selected_idx = choose_option(channel, options, ask_prompt="Please choose new vultr to create: ")
        user_selected = options[user_selected_idx]
        logger.info(f"choose vultr, user selected: {user_selected_idx}: {user_selected}")
        if user_selected_idx == 0:
            return self._manually_create_new_node(channel)
        region_id, plan_id, image_id = user_selected.split(":")
        return region_id, plan_id, image_id

    def _manually_create_new_node(self, channel) -> Tuple[str, str, str]:
        send_to_channel(channel, "Fetching metadata from vultr...")
        regions: List[Region] = [i for i in self.client.region.list()]
        plans: List[Plan] = [i for i in self.client.plan.list()]
        oses: List[OS] = [i for i in self.client.operating_system.list()]

        region_slugs = [f"{r.id:3} - {r.city:15} | country: {r.country:3} | Position: {r.continent:5}" for r in regions]
        selected_region_idx = choose_option(channel, region_slugs, ask_prompt="Please choose region: ")
        selected_region: Region = regions[selected_region_idx]

        size_slugs = [
            (
                f"{t.id:15} | Disk: {t.disk:5} GB, Disk count: {t.disk_count} | Mem: {t.ram:6} MB | "
                f"Month Price($): {t.monthly_cost:5}"
            )
            for t in plans
        ]
        selected_plan_idx = choose_option(channel, size_slugs, ask_prompt="Please choose vultr plan: ")
        selected_plan: Plan = plans[selected_plan_idx]

        os_options = [f"{i.id:4} | arch: {i.arch:5} | family: {i.family:15} | name: {i.name}" for i in oses]
        selected_image_idx = choose_option(channel, os_options, ask_prompt="Please choose vultr image: ")
        selected_images: OS = oses[selected_image_idx]

        return selected_region.id, selected_plan.id, str(selected_images.id)

    def destroy_server(self, meta: LBServerMeta, channel: Channel = None) -> bool:
        logger.info(f"try to destroy {meta.server_name} under workspace {meta.workspace}...")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name}...")
        data = self.load_raw_server(meta.workspace)

        failed = self.client.instance.delete(instance_id=data["id"])
        success = not failed
        logger.info(f"destroy vultr, result: {success}")
        if channel:
            send_to_channel(channel, f"Destroy server {meta.server_name} done.")
        return success
