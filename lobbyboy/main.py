#!/usr/bin/env python

import argparse
import logging
import socket
import sys
import threading
import traceback
from pathlib import Path
from typing import Dict

from lobbyboy.config import LBConfig
from lobbyboy.config import LBConfig, LBConfigProvider, load_config
from lobbyboy.provider import BaseProvider
from lobbyboy.server_killer import ServerKiller
from lobbyboy.socket_handle import SocketHandlerThread
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

    # Load config.
    config: LBConfig = LBConfig.load(Path(args.config_path))
    # Init providers instances.
    providers = {
        provider_name: cls(
            name=provider_name,
            config=config.provider[provider_name],
            workspace=config.data_dir.joinpath(provider_name),
        )
        for provider_name, cls in config.provider_cls.items()
    }

    # Setup log.
    setup_logs(logging.getLevelName(config.log_level))
    confirm_ssh_key_pair(config.data_dir, key_name="ssh_host_rsa_key")

    # Prepare socket.
    sock: socket = prepare_socket(config.listen_ip, config.listen_port)

    # Set killer.
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
