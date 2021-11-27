#!/usr/bin/env python

import argparse
import importlib
import logging
import socket
import sys
import threading
import traceback
from pathlib import Path
from typing import Dict

from lobbyboy.config import LBConfig, load_config, LBConfigProvider
from lobbyboy.provider import BaseProvider
from lobbyboy.socket_handle import SocketHandlerThread
from lobbyboy.server_killer import ServerKiller
from lobbyboy.utils import confirm_ssh_key_pair, to_seconds

# TODO generate all keys when start, if key not exist.
# TODO fix server threading problems (no sleep!)
# TODO support sync server from provider, add destroy manage flag on those server


logger = logging.getLogger(__name__)


def setup_logs(level=logging.DEBUG):
    """send paramiko logs to a logfile,
    if they're not already going somewhere"""

    frm = "%(levelname)-.3s [%(asctime)s.%(msecs)03d] thr=%(thread)d %(name)s:%(lineno)d: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(frm, "%Y%m%d-%H:%M:%S"))
    logging.basicConfig(level=level, handlers=[handler])


def load_providers(provider_configs: Dict[str, LBConfigProvider], head_workspace: Path) -> Dict:
    """
    Args:
        provider_configs: provider config loaded from provider part of config file
        head_workspace: workspace for all provider

    Returns:
        dict: provider name -> provider instance
    """
    from lobbyboy.provider import BaseProvider

    _providers: Dict[str, BaseProvider] = {}

    head_workspace.mkdir(parents=True, exist_ok=True)
    for name, config in provider_configs.items():
        module_path, classname = config.load_module.split("::", maxsplit=1)
        logger.debug(f"loading path: {module_path}, classname: {classname}")

        module = importlib.import_module(module_path)
        provider_cls = getattr(module, classname)
        _providers[name] = provider_cls(name=name, config=config, workspace=head_workspace.joinpath(name))

    logger.info(f"{len(_providers)} providers loaded: {_providers.keys()}")
    return _providers


def prepare_socket(listen_ip: str, listen_port: int) -> socket:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        logger.info("start listen on %s:%s...", listen_ip, listen_port)
        sock.bind((listen_ip, listen_port))
    except Exception as e:
        logger.error(f"*** Bind failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        sock.listen(100)
    except Exception as e:
        logger.error(f"*** Listen failed: {e}")
        traceback.print_exc()
        sys.exit(1)
    logger.info(f"Listening for connection on {listen_ip}:{listen_port} ...")
    return sock


def runserver(sock: socket, conf: LBConfig, providers: Dict[str, BaseProvider]):
    while 1:
        try:
            client, address = sock.accept()
        except Exception as e:
            logger.error(f"*** Accept new socket failed: {e}")
            continue
        logger.info(f"get a connection, from address: {address}")
        SocketHandlerThread(client, address, conf, providers).start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", dest="config_path", help="config file path", required=True)
    args = parser.parse_args()

    # load config
    config: LBConfig = load_config(Path(args.config_path))

    # setup log
    setup_logs(logging.getLevelName(config.log_level))
    # confirmation local private key
    confirm_ssh_key_pair(save_path=config.data_dir)
    # init provider
    providers: Dict[str, BaseProvider] = load_providers(config.provider, config.data_dir)
    # prepare socket
    sock = prepare_socket(config.listen_ip, config.listen_port)

    # set killer
    killer = ServerKiller(providers, config.servers_db_path)
    killer_thread = threading.Thread(
        target=killer.patrol,
        args=(to_seconds(config.min_destroy_interval),),
        daemon=True,
    )
    killer_thread.start()
    logger.info(f"started server_killer thread: {killer_thread}")

    runserver(sock, config, providers)


if __name__ == "__main__":
    main()
