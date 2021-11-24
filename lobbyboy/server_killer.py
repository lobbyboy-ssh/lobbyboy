import logging
import time
from pathlib import Path
from typing import Dict, OrderedDict, Tuple

from paramiko import Channel

from lobbyboy.provider import BaseProvider
from lobbyboy.utils import available_server_db_lock, humanize_seconds, active_session, to_seconds
from lobbyboy.config import LBConfigProvider, LBServerMeta, LBConfig

logger = logging.getLogger(__name__)


class ServerKiller:
    def __init__(self, watched_providers: Dict[str, BaseProvider], servers_db_path: Path):
        self.servers_db_path: Path = servers_db_path
        self.watched_providers: Dict[str, BaseProvider] = watched_providers

    def patrol(self, cycle_sec: int = 1 * 60):
        while 1:
            logger.info(f"killer start a new {cycle_sec} seconds round...")
            self.check_all_live_servers()
            time.sleep(cycle_sec)

    def check_all_live_servers(self):
        metas: OrderedDict[str, LBServerMeta] = LBConfig.load_local_servers(self.servers_db_path)

        for server_name, meta in metas.items():
            provider: BaseProvider
            provider = self.watched_providers.get(meta.provider_name)
            if not provider:
                logger.error(f"can't find provider of server {meta.server_name}, destroy check failed.")
                raise Exception

            need_to_be_destroy, reason = self.need_destroy(provider, meta)
            logger.info(f"{server_name} need to be destroyed? {need_to_be_destroy}, reason: {reason}.")
            if need_to_be_destroy:
                self.destroy(provider, meta)

    @classmethod
    def need_destroy(cls, provider: BaseProvider, meta: LBServerMeta) -> Tuple[bool, str]:
        """
        check if a provider's server need to be destroyed or not.

        Args:
            provider: provider, provider info
            meta: LBServerMeta, server meta info

        Returns:
            tuple, (need_to_be_destroy: bool, reason: str)
        """
        # check whether there is an activity session first
        active_sessions = active_session.get(meta.server_name, [])
        active_session_cnt = len(active_sessions)
        if active_session_cnt > 0:
            return False, f"still have {active_session_cnt} active sessions."

        if not meta.manage:
            return False, f"server {meta.server_name} has flag not manage by me."

        config: LBConfigProvider = provider.provider_config
        # check whether the minimum life cycle is reached
        min_life_to_live_in_sec = to_seconds(config.min_life_to_live)
        if min_life_to_live_in_sec <= 0:
            return True, f"min_life_to_live less or equal 0: {min_life_to_live_in_sec}."
        ttl = min_life_to_live_in_sec - meta.live_sec
        if ttl > 0:
            return False, f"still have {humanize_seconds(ttl)} to live(min_life_to_live={config.min_life_to_live})."

        # check whether it should be destroyed within a reasonable bill cycle.
        bill_time_unit_in_sec = to_seconds(config.bill_time_unit)
        cur_bill_live_time = meta.live_sec % bill_time_unit_in_sec
        destroy_safe_time_in_sec = to_seconds(config.destroy_safe_time) if config.destroy_safe_time else 0
        ttl = bill_time_unit_in_sec - cur_bill_live_time - destroy_safe_time_in_sec
        if ttl > 0:
            return False, f"still have {humanize_seconds(ttl)} to live(bill_time_unit={config.bill_time_unit})."

        return True, "is about to enter the next billing cycle."

    def destroy(self, provider: BaseProvider, meta: LBServerMeta, channel: Channel = None):
        """
        Args:
            provider: provider instance, object
            meta: server data dict
            channel: paramiko.Transport, optional, if not None, will send destroy message to this channel
        """
        if not meta.manage:
            raise Exception(f"destroy failed, provider {provider.name} server {meta.server_name} not manage by me!")
        provider.destroy_server(meta, channel)
        with available_server_db_lock:
            LBConfig.update_local_servers(self.servers_db_path, deleted=[meta])
