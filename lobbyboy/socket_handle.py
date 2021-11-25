from io import StringIO
from typing import OrderedDict, Tuple, Optional

import os
import socket
import threading
import select
import logging
from binascii import hexlify
from typing import Dict

from subprocess import Popen

import paramiko
from paramiko.channel import Channel
from paramiko.transport import Transport

from lobbyboy.server import Server
from lobbyboy.server_killer import ServerKiller
from lobbyboy.utils import (
    available_server_db_lock,
    active_session_lock,
    DoGSSAPIKeyExchange,
    send_to_channel,
    active_session,
    KeyTypeSupport,
    choose_option,
    confirm_ssh_key_pair,
)
from lobbyboy.config import LBConfig, LBServerMeta
from lobbyboy.exceptions import UserCancelException, ProviderException, NoProviderException
from lobbyboy.provider import BaseProvider
from lobbyboy import __version__

logger = logging.getLogger(__name__)


class SocketHandlerThread(threading.Thread):
    def __init__(self, sock: socket, address, config: LBConfig, providers: Dict[str, BaseProvider]) -> None:
        super().__init__()
        self.socket_client = sock
        self.client_address = address
        self.config = config
        self.providers: Dict[str, BaseProvider] = providers
        self.killer = ServerKiller(providers, config.servers_db_path)
        self.channel: Optional[Channel] = None

    def choose_providers(self) -> BaseProvider:
        if not self.providers:
            send_to_channel(self.channel, "There is no available providers.")
            raise NoProviderException("Do not have available providers to provision a new server!")

        user_input = choose_option(
            self.channel,
            list(self.providers.keys()),
            option_prompt="Available VPS providers:",
            ask_prompt="Please choose a provider to create a new server: ",
        )
        return list(self.providers.values())[user_input]

    def choose_server(self) -> LBServerMeta:
        available_servers: OrderedDict[str, LBServerMeta] = LBConfig.load_local_servers(self.config.servers_db_path)
        if not available_servers:
            send_to_channel(self.channel, "There is no available servers, provision a new server...")
            return self._ask_user_to_create_server()

        options = ["Create a new server..."]
        meta: LBServerMeta
        for meta in available_servers.values():
            server_desc = f"{meta.provider_name} {meta.server_name} {meta.server_host}"
            sessions_cnt = len(active_session.get(meta.server_name, []))
            options.append(f"Enter {server_desc} ({sessions_cnt} active sessions)")
        user_input = choose_option(
            self.channel,
            options,
            option_prompt=f"There are {len(available_servers)} available servers:",
        )

        logger.info(f"user choose server input={user_input}.")
        if user_input == 0:
            return self._ask_user_to_create_server()
        user_input -= 1
        return list(available_servers.values())[user_input]

    def _ask_user_to_create_server(self) -> LBServerMeta:
        provider: BaseProvider = self.choose_providers()
        meta: LBServerMeta = provider.create_server(self.channel)
        with available_server_db_lock:
            LBConfig.update_local_servers(self.config.servers_db_path, new=[meta])
        return meta

    def _create_proxy_process(self, slave_fd) -> Tuple[Popen, LBServerMeta]:
        # if has available servers, prompt login or create
        # if no, create, and redirect
        meta: LBServerMeta = self.choose_server()
        provider = self.providers.get(meta.provider_name)
        if not provider:
            raise NoProviderException(f"not find provider for server {meta.server_name}")

        ssh_command_units = provider.ssh_server_command(meta)
        ssh_command = " ".join(str(i) for i in ssh_command_units)
        logger.info(f"ssh to server {meta.server_name} {meta.server_host}: {ssh_command}")
        send_to_channel(
            self.channel,
            f"Redirect you to {meta.provider_name} server: {meta.server_name} ({meta.server_host})...",
        )
        proxy_subprocess = Popen(
            ssh_command,
            shell=True,
            preexec_fn=os.setsid,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            universal_newlines=True,
        )
        with active_session_lock:
            active_session.setdefault(meta.server_name, []).append(self.channel.get_transport())
        return proxy_subprocess, meta

    def prepare_server(self, t: Transport, key_type: KeyTypeSupport = KeyTypeSupport.RSA) -> Optional[Server]:
        try:
            t.load_server_moduli()
        except:  # noqa
            logger.error("(Failed to load moduli -- gex will be unsupported.)")
            raise

        pri, _ = confirm_ssh_key_pair(key_type=key_type, save_path=self.config.data_dir)
        host_key = paramiko.RSAKey.from_private_key(StringIO(pri))

        logger.info("Read host key: " + hexlify(host_key.get_fingerprint()).decode())
        t.add_server_key(host_key)

        server = Server(self.config)
        try:
            t.start_server(server=server)
        except paramiko.SSHException:
            logger.error("*** SSH negotiation failed.")
            logger.error(f"close the transport now... {t}")
            return

        self.channel = t.accept(timeout=20)
        if self.channel is None:
            logger.error("Client never open a new channel, close transport now...")
            return
        return server

    def prepare_shell_env(self, server: Server, t: Transport) -> Tuple[Optional[LBServerMeta], Optional[Popen]]:
        server.shell_event.wait()
        if not server.shell_event.is_set():
            logger.warning("Client never asked for a shell, I am going to end this ssh session now...")
            send_to_channel(
                self.channel,
                "*** Client never asked for a shell. Server will end session...",
            )
            return None, None

        logger.info(f"transport peer name: {t.getpeername()}")
        proxy_subprocess = lb_server = None
        try:
            proxy_subprocess, lb_server = self._create_proxy_process(server.slave_fd)
        except UserCancelException:
            logger.warning("user input Ctrl-C or Ctrl-D during the input.")
            send_to_channel(self.channel, "Got EOF, closing session...")
        except ProviderException as e:
            logger.warning(f"got exceptions from provider: {e}")
            send_to_channel(self.channel, f"LobbyBoy got exceptions from provider: {e}")
        if not (proxy_subprocess and lb_server):
            return None, None

        logger.info(f"proxy subprocess created, pid={proxy_subprocess.pid}")
        server.proxy_subprocess_pid = proxy_subprocess.pid

        send_to_channel(self.channel, int(server.window_width) * "=")
        return lb_server, proxy_subprocess

    def user_using(self, server: Server, proxy_subprocess: Popen):
        channel_fd = self.channel.fileno()
        master_fd = server.master_fd
        while proxy_subprocess.poll() is None:
            r, *_ = select.select([master_fd, channel_fd], [], [], 0.1)
            if master_fd in r:
                send_to_channel(self.channel, os.read(master_fd, 10240).decode(), suffix="")
            elif channel_fd in r:
                os.write(master_fd, self.channel.recv(10240))

    def cleanup(self, t: Transport = None, meta: LBServerMeta = None, check_destroy: bool = False):
        if t and meta:
            self.remove_server_session(t, meta.server_name)
            if check_destroy:
                self.destroy_server_if_needed(meta)

        if self.channel:
            self.channel.shutdown(0)
        if t:
            t.close()

    def destroy_server_if_needed(self, server: LBServerMeta):
        provider = self.providers[server.provider_name]
        need_destroy, reason = self.killer.need_destroy(provider, server)
        send_to_channel(self.channel, f"LobbyBoy: This server {reason}.")
        if not need_destroy:
            return

        send_to_channel(self.channel, f"LobbyBoy: I will destroy {server.server_name}({server.server_host}) now!")
        self.killer.destroy(provider, server, self.channel)
        send_to_channel(
            self.channel,
            f"LobbyBoy: Server {server.server_name}({server.server_host}) has been destroyed.",
        )

    @staticmethod
    def remove_server_session(transport: Transport, server_name: str):
        peer_name = transport.getpeername()
        with active_session_lock:
            sessions = active_session.get(server_name)
            if sessions:
                active_session[server_name] = list(filter(lambda x: x.getpeername() != peer_name, sessions))

    def run(self):
        logger.info(
            f"start new thread "
            f"handle {self.socket_client}, "
            f"address: {self.client_address}, "
            f"my thread id={threading.get_ident()}"
        )
        t = Transport(self.socket_client, gss_kex=DoGSSAPIKeyExchange)
        try:
            t.set_gss_host(socket.getfqdn())
            server = self.prepare_server(t)
            if not (server and self.channel):
                self.cleanup(t)
                return

            send_to_channel(self.channel, f"Welcome to LobbyBoy {__version__}!")
            lb_server, proxy_subprocess = self.prepare_shell_env(server, t)
            if not (proxy_subprocess and lb_server):
                logger.error("failed to create proxy subprocess or lb_server")
                self.cleanup(t, meta=lb_server)
                return

            self.user_using(server, proxy_subprocess)
            send_to_channel(
                self.channel,
                f"LobbyBoy: SSH to remote server {lb_server.server_name} closed.",
            )
            self.cleanup(t, meta=lb_server, check_destroy=True)
        except Exception:  # noqa
            logger.critical("*** Socket thread error.", exc_info=True)
            self.cleanup(t)
