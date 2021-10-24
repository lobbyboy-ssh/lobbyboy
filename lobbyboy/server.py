#!/usr/bin/env python
import re
import time
import json
import base64
import os
import socket
import sys
import threading
import traceback
import select
import termios
import pty
import struct
import fcntl
import signal
import termios
import struct
import fcntl
import logging
import argparse
import importlib
from binascii import hexlify
from pathlib import Path

import paramiko
from paramiko import AUTH_SUCCESSFUL, AUTH_FAILED
from subprocess import Popen

from .config import load_config
from . import exceptions


DoGSSAPIKeyExchange = True
# openssh ssh-keygen: The default length is 3072 bits (RSA) or 256 bits (ECDSA).
DEFAULT_HOST_RSA_BITS = 3072
# {server_id: [Transport]}
active_session = {}
available_server_db_lock = threading.Lock()
active_sesion_lock = threading.Lock()


def setup_logs(level=logging.DEBUG):
    """send paramiko logs to a logfile,
    if they're not already going somewhere"""
    frm = "%(levelname)-.3s [%(asctime)s.%(msecs)03d] thr=%(thread)d"
    frm += " %(name)s: %(message)s"
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(frm, "%Y%m%d-%H:%M:%S"))
    logging.basicConfig(level=level, handlers=[handler])


setup_logs()
logger = logging.getLogger(__name__)


def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


# TODO generate all keys when start, if key not exist.
# TODO fix server threading problems (no sleep!)


class Server(paramiko.ServerInterface):
    def __init__(self, config, providers):
        self.pty_event = threading.Event()
        self.shell_event = threading.Event()
        self.config = config
        self.window_width = self.window_height = 0
        self.proxy_subprocess = None
        self.client_exec = None
        self.client_exec_provider = None
        self.providers = providers
        self.master_id = self.slave_fd = None

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        # TODO load config file every time.
        if (username == "robey") and (password == "foo"):
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def _get_key_class(self, key_type):
        if key_type == "ssh-rsa":
            return paramiko.RSAKey
        # TODO other types
        raise Exception("Unknown key type")

    def check_auth_publickey(self, username, key):
        key_type = key.get_name()
        logger.info("try to auth {} with key type {}...".format(username, key_type))
        reloaded_config = load_config(self.config["__config_path__"])
        keys_string = reloaded_config["user"][username]["authorized_keys"]
        key_cls = self._get_key_class(key_type)
        for line in keys_string.split("\n"):
            if not line.startswith(key_type):
                continue
            _, _key_pub = line.split(" ", 2)
            accept_key = key_cls(data=base64.b64decode(_key_pub))
            logger.info(
                "try to auth {} with key {}".format(
                    username, hexlify(accept_key.get_fingerprint()).decode()
                )
            )
            if key == accept_key:
                logger.info(
                    "accept auth {} with key {}".format(
                        username, hexlify(accept_key.get_fingerprint()).decode()
                    )
                )
                return AUTH_SUCCESSFUL
        logger.info("Can not auth {} with any key.".format(username))
        return AUTH_FAILED

    def check_auth_gssapi_with_mic(
        self, username, gss_authenticated=AUTH_FAILED, cc_file=None
    ):
        """
        .. note::
            We are just checking in `AuthHandler` that the given user is a
            valid krb5 principal! We don't check if the krb5 principal is
            allowed to log in on the server, because there is no way to do that
            in python. So if you develop your own SSH server with paramiko for
            a certain platform like Linux, you should call ``krb5_kuserok()`` in
            your local kerberos library to make sure that the krb5_principal
            has an account on the server and is allowed to log in as a user.

        .. seealso::
            `krb5_kuserok() man page
            <http://www.unix.com/man-page/all/3/krb5_kuserok/>`_
        """
        if gss_authenticated == paramiko.AUTH_SUCCESSFUL:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_gssapi_keyex(
        self, username, gss_authenticated=AUTH_FAILED, cc_file=None
    ):
        # TODO
        if gss_authenticated == AUTH_SUCCESSFUL:
            logger.info("gss auth success")
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def enable_auth_gssapi(self):
        return True

    def get_allowed_auths(self, username):
        return "gssapi-keyex,gssapi-with-mic,password,publickey"

    def check_channel_shell_request(self, channel):
        logger.info("client request shell...")
        self.pty_event.wait(10)
        if not self.pty_event.is_set():
            logger.error("Client never ask a tty, can not allocate shell...")
            raise Exception("No TTY")
        self.shell_event.set()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        logger.info(
            "Client request pty..., term={} width={}, height={}, pixelwidth={}, pixelheight={}".format(
                term, width, height, pixelwidth, pixelwidth
            )
        )
        self.master_fd, self.slave_fd = pty.openpty()
        logger.debug(
            "user's pty ready, master_fd={}, slave_fd={}".format(
                self.master_fd, self.slave_fd
            )
        )
        self.window_width = width
        self.window_height = height
        set_winsize(self.master_fd, height, width, pixelwidth, pixelheight)
        self.pty_event.set()
        return True

    def check_channel_window_change_request(
        self, channel, width, height, pixelwidth, pixelheight
    ):
        logger.debug(
            "client send window size change reuqest... width={}, height={}, pixelwidth={}, pixelheight={}".format(
                width,
                height,
                pixelwidth,
                pixelheight,
            )
        )
        self.window_width = width
        self.window_height = height
        set_winsize(self.master_fd, height, width, pixelwidth, pixelheight)

        if self.proxy_subprocess:
            os.kill(self.proxy_subprocess, signal.SIGWINCH)
        return True


def evict_active_session(transport, serverid):
    with active_sesion_lock:
        session_list = active_session[serverid]
        active_session[serverid] = [
            _t for _t in session_list if _t.getpeername() != transport.getpeername()
        ]
        return


class SocketHandlerThread(threading.Thread):
    def __init__(self, socket_client, client_addr, config, providers) -> None:
        """
        Args:
            socket_client, client_addr: created by socket.accept()
        """
        self.socket_client = socket_client
        self.client_addr = client_addr
        self.config = config
        self.providers = providers
        super().__init__()

    def run(self):
        logger.info(
            "start new thread handle {}, addr: {}, my thread id={}".format(
                self.socket_client, self.client_addr, threading.get_ident()
            )
        )
        t = paramiko.Transport(self.socket_client, gss_kex=DoGSSAPIKeyExchange)
        try:
            t.set_gss_host(socket.getfqdn(""))
            try:
                t.load_server_moduli()
            except:
                logger.error("(Failed to load moduli -- gex will be unsupported.)")
                raise
            host_key = paramiko.RSAKey(
                filename=str(Path(self.config["data_dir"]) / "ssh_host_rsa_key")
            )
            logger.info(
                "Read host key: " + hexlify(host_key.get_fingerprint()).decode()
            )
            t.add_server_key(host_key)
            server = Server(self.config, self.providers)
            try:
                t.start_server(server=server)
            except paramiko.SSHException:
                logger.error("*** SSH negotiation failed.")
                logger.error("close the transport now... {}".format(t))
                t.close()
                return

            chan = t.accept(20)
            if chan is None:
                logger.error("Client never open a new channel, close transport now...")
                t.close()
                return

            server.shell_event.wait()
            if not server.shell_event.is_set():
                logger.warn(
                    "Client never asked for a shell, I am going to end this ssh session now..."
                )
                chan.send(
                    b"*** Client never asked for a shell. Server will end session...\r\n"
                )
                t.close()
                return

            master_fd = server.master_fd
            slave_fd = server.slave_fd
            logger.info("transport peer name: {}".format(t.getpeername()))
            try:
                p, serverid, provider = self._create_proxy_process(chan, slave_fd)
            except exceptions.UserCancelException:
                logger.warn("user input Ctrl-C or Ctrl-D during the input.")
                chan.send("Got EOF, closing session...\r\n".encode())
                chan.close()
                evict_active_session(t, serverid)
                t.close()
                return

            logger.info("open subprocess...")
            chan.send((int(server.window_width) * "=" + "\r\n").encode())
            chan_fd = chan.fileno()
            while p.poll() is None:
                r, w, e = select.select([master_fd, chan_fd], [], [], 0.1)
                if master_fd in r:
                    d = os.read(master_fd, 10240)
                    chan.send(d)
                elif chan_fd in r:
                    o = chan.recv(10240)
                    os.write(master_fd, o)

            chan.send("Lobbyboy: SSH to remote server {} closed.\r\n".format(serverid).encode())
            evict_active_session(t, serverid)
            self.destroy_server_if_needed(serverid, chan)
            chan.shutdown(0)
            t.close()

        except Exception as e:
            logger.error("*** Caught exception: " + str(e.__class__) + ": " + str(e))
            traceback.print_exc()
            try:
                evict_active_session(t, serverid)
                t.close()
            except:
                pass

    def load_server_info(self, serverid):
        servers = self._load_availiable_server()
        for server in servers:
            if server["server_id"] == serverid:
                return server
        raise Exception("serverid={} not found!".format(serverid))

    def _parse_time_config(self, timestr):
        """
        Args:
            timestr: str, 10s, 10m, 10h, 10d
        Returns:
            seconds
        """
        matched = re.match(r"(\d+)s", timestr)
        if matched:
            return int(matched.group(1))

        matched = re.match(r"(\d+)m", timestr)
        if matched:
            return int(matched.group(1)) * 60

        matched = re.match(r"(\d+)h", timestr)
        if matched:
            return int(matched.group(1)) * 60 * 60

        matched = re.match(r"(\d+)d", timestr)
        if matched:
            return int(matched.group(1)) * 60 * 60 * 24

        raise Exception("Can not parse {}".format(timestr))

    def _human_time(self, seconds: int):
        return "{}s".format(seconds)

    def delete_from_server_db(self, serverid):
        with available_server_db_lock:
            servers = self._load_availiable_server()
            new_servers = [s for s in servers if s['server_id'] != serverid]
            json.dump(
                new_servers,
                open(Path(self.config["data_dir"]) / "available_servers.json", "w+"),
            )

    def destroy_server_if_needed(self, serverid, channel):
        server = self.load_server_info(serverid)
        provider_name = server["provider"]
        pconfig = self.config["provider"][provider_name]

        born_time = server["created_timestamp"]
        lived_time = time.time() - born_time
        min_life_to_live_seconds = self._parse_time_config(pconfig["min_life_to_live"])
        if min_life_to_live_seconds == 0:
            channel.send("I will destroy {}({}) now! (min_life_to_live=0)\r\n".format(serverid, server['server_host']).encode())
            provider = self.providers[provider_name]
            provider.destroy_server(serverid, server['server_host'], channel)
            self.delete_from_server_db(serverid)
            channel.send("Server has been destroyed.\r\n".encode())
            return 
        bill_time_unit = self._parse_time_config(pconfig["bill_time_unit"])

        FIVE_MINUTES = 5 * 60
        destroy_spare_seconds = max(
            [self._parse_time_config(self.config["destroy_interval"]), FIVE_MINUTES]
        )
        bill_unit_left_time = (
            bill_time_unit - destroy_spare_seconds - (lived_time % bill_time_unit)
        )

        min_live_left_seconds = min_life_to_live_seconds - lived_time
        if min_live_left_seconds > 0:
            channel.send(
                "I will try to destroy the server after {} (min_life_to_live={})...\r\n".format(
                    self._human_time(min_life_to_live_seconds),
                    pconfig["min_life_to_live"],
                )
            )
            return
        if bill_unit_left_time > 0:
            channel.send(
                "I will try to destroy the server after {} (min_life_to_live={})...\r\n".format(
                    self._human_time(bill_unit_left_time),
                    pconfig["bill_time_unit"],
                )
            )
            return
        channel.send("I will destroy {}({}) now!\r\n".format(serverid, server['server_host']).encode())
        provider = self.providers[provider_name]
        provider.destroy_server(serverid, server['server_host'], channel)
        self.delete_from_server_db(serverid)
        channel.send("Server has been destroyed.".encode())


    def _create_proxy_process(self, channel, slave_fd):
        # if has available servers, prompt login or create
        # if no,  create, and redirect
        available_servers = self._load_availiable_server()
        if available_servers:
            channel.send(
                "There are {} available servers:\r\n".format(
                    len(available_servers)
                ).encode()
            )
            channel.send("{:>3} - Create a new server...\r\n".format(0))
            for index, server in enumerate(available_servers):
                channel.send(
                    "{:>3} - Enter {} {} ({} active sessions)\r\n".format(
                        index + 1,
                        server["server_id"],
                        server["server_host"],
                        len(active_session.get(server["server_id"], [])),
                    )
                )
            channel.send("Please input your choice (number): ".encode())
            user_input = int(self.read_user_input_line(channel))
            if user_input == 0:
                logger.info("userinput=0, wants to create a new server...")
                serverid, serverhost, provider = self._create_new_server(channel)
            else:
                user_input -= 1
                logger.info(
                    "userinput={}, wants to ssh to an exist server...".format(
                        user_input
                    )
                )
                choosed_server = available_servers[user_input]
                serverid = choosed_server["server_id"]
                serverhost = choosed_server["server_host"]
                provider_name = choosed_server["provider"]
                provider = self.providers[provider_name]
        else:
            channel.send("There is no available servers, provision a new server...\r\n")
            serverid, serverhost, provider = self._create_new_server(channel)
        ssh_command = provider.ssh_server_command(serverid, serverhost)
        logger.info(
            "ssh to server {} {}: {}".format(
                serverid, serverhost, " ".join(ssh_command)
            )
        )
        channel.send(
            "Redirect you to {} ({})...\r\n".format(serverid, serverhost).encode()
        )
        proxy_subprocess = Popen(
            ssh_command,
            preexec_fn=os.setsid,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            universal_newlines=True,
        )
        with active_sesion_lock:
            active_session.setdefault(serverid, []).append(channel.get_transport())
        return proxy_subprocess, serverid, provider

    def choose_providers(self, channel):
        if len(self.providers) < 1:
            raise Exception(
                "Do not have available providers to provision a new server!"
            )
        elif len(self.providers) == 1:
            return self.providers.values()[0]
        else:
            pnames = list(self.providers.keys())
            channel.send("Available VPS providers:\r\n")
            for index, name in enumerate(pnames):
                channel.send("{:>3} - {}\r\n".format(index, name))
            channel.send("Please choose a provider to create a new server: ")
            user_input = self.read_user_input_line(channel)
            choosed_provider_name = pnames[int(user_input)]
            return self.providers[choosed_provider_name]

    def _create_new_server(self, chan):
        provider = self.choose_providers(chan)
        server_id, server_ip = provider.new_server(chan)
        with available_server_db_lock:
            server_json = self._load_availiable_server()
            if not server_json:
                server_json = []

            server_json.append(
                {
                    "server_id": server_id,
                    "server_host": server_ip,
                    "provider": provider.provider_name,
                    "created_timestamp": time.time(),
                }
            )
            json.dump(
                server_json,
                open(Path(self.config["data_dir"]) / "available_servers.json", "w+"),
            )

        return server_id, server_ip, provider

    def _load_availiable_server(self):
        try:
            server_json = json.load(
                open(Path(self.config["data_dir"]) / "available_servers.json", "r+")
            )
        except Exception as e:
            logger.error("Error when reading available_servers.json, {}".format(str(e)))
            return []
        logger.debug(
            "open server_json, find {} available_servers: {}".format(
                len(server_json), server_json
            )
        )
        return server_json

    def read_user_input_line(self, chan):
        # TODO do not support del
        logger.debug("reading from channel... {}".format(chan))
        chars = []
        while 1:
            content = chan.recv(1)
            logger.debug("channel recv: {}".format(content))
            if content == b"\r":
                chan.send(b"\r\n")
                break
            if content == b"\x04" or content == b"\x03":
                raise exceptions.UserCancelException()
            chan.send(content)
            chars.append(content)
        return b"".join(chars).decode()


def runserver(config, providers):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((config["listen_ip"], config["listen_port"]))
    except Exception as e:
        logger.error("*** Bind failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)

    try:
        sock.listen(100)
    except Exception as e:
        logger.error("*** Listen failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    while 1:
        logger.info("Listening for connection ...")
        try:
            client, addr = sock.accept()
        except Exception as e:
            logger.error("*** Accept new socket failed: " + str(e))
            continue
        logger.info("get a connection, from addr: {}".format(addr))
        SocketHandlerThread(client, addr, config, providers).start()


def generate_host_keys(data_dir):
    """
    check host_key exist in data_dir, if not, generate
    """
    # TODO support new key type: dss, Ed25519, ECDSA
    path = Path(data_dir) / "ssh_host_rsa_key"
    if not path.exists():
        logger.info("Host key do not exist, generate to {}...".format(str(path)))
        rsa_key = paramiko.RSAKey.generate(DEFAULT_HOST_RSA_BITS)
        rsa_key.write_private_key_file(str(path))


def load_providers(config):
    _providers = {}
    for name, pconfig in config["provider"].items():
        path = pconfig["loadmodule"]
        module_path, classname = path.split("::")
        logger.debug("loading path: {}, classname: {}".format(module_path, classname))
        module = importlib.import_module(module_path)
        provider_work_path = Path(config["data_dir"]) / name
        if not provider_work_path.exists():
            logger.info(
                "{}'s workpath {} don't exist, creating...".format(
                    name, str(provider_work_path)
                )
            )
            os.mkdir(str(provider_work_path))
        provider_obj = getattr(module, classname)(
            provider_name=name,
            config=config,
            provider_config=pconfig,
            data_path=str(provider_work_path),
        )
        _providers[name] = provider_obj

    logger.info("{} providers loaded: {}".format(len(_providers), _providers.keys()))

    return _providers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", dest="config_path", help="config file path", required=True
    )
    args = parser.parse_args()
    config = load_config(args.config_path)
    config["__config_path__"] = args.config_path
    generate_host_keys(config["data_dir"])
    providers = load_providers(config)
    runserver(config, providers)
