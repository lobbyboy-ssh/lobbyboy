#!/usr/bin/env python
import time
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
from binascii import hexlify
from pathlib import Path

import paramiko
from paramiko.py3compat import decodebytes
from paramiko import AUTH_SUCCESSFUL, AUTH_FAILED
from subprocess import Popen

from .config import load_config


DoGSSAPIKeyExchange = True
# openssh ssh-keygen: The default length is 3072 bits (RSA) or 256 bits (ECDSA).
DEFAULT_HOST_RSA_BITS = 3072


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
    def __init__(self, config):
        self.pty_event = threading.Event()
        self.shell_event = threading.Event()
        self.config = config

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
        keys_string = reloaded_config["users"][username]["authorized_keys"]
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
            return paramiko.AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_gssapi_keyex(
        self, username, gss_authenticated=AUTH_FAILED, cc_file=None
    ):
        # TODO
        if gss_authenticated == paramiko.AUTH_SUCCESSFUL:
            logger.info("gss auth success")
            return paramiko.AUTH_SUCCESSFUL
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
        # if has available servers, prompt login or create
        # if no,  create, and redirect

        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        logger.info(
            "Client request pty..., term={} width={}, height={}, pixelwidth={}, pixelheight={}, modes={}".format(
                term, width, height, pixelwidth, pixelwidth, modes
            )
        )
        self.master_fd, self.slave_fd = pty.openpty()
        logger.debug(
            "user's pty ready, master_fd={}, slave_fd={}".format(
                self.master_fd, self.slave_fd
            )
        )
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
        set_winsize(self.master_fd, height, width, pixelwidth, pixelheight)
        # os.kill(self.pid, signal.SIGWINCH)
        return True


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
            server = Server(self.config)
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

            server.shell_event.wait(10)
            if not server.shell_event.is_set():
                logger.warn(
                    "Client never asked for a shell, I am going to end this ssh session now..."
                )
                chan.send(
                    b"*** Client never asked for a shell. Server will end session...\r\n"
                )
                t.close()
                return

            command = [
                "ssh",
                "-i",
                "/Users/xintao.lai/Programs/tlpi-code/.vagrant/machines/default/virtualbox/private_key",
                "-p",
                "2222",
                "vagrant@127.0.0.1",
                "-t",
            ]

            # open pseudo-terminal to interact with subprocess

            time.sleep(3)
            master_fd, slave_fd = server.master_fd, server.slave_fd

            p = Popen(
                command,
                preexec_fn=os.setsid,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                universal_newlines=True,
            )
            server.pid = p.pid

            logger.info("open subprocess...")
            chan_fd = chan.fileno()
            while p.poll() is None:
                r, w, e = select.select([master_fd, chan_fd], [], [], 0.1)
                if master_fd in r:
                    d = os.read(master_fd, 10240)
                    chan.send(d)
                elif chan_fd in r:
                    o = chan.recv(10240)
                    os.write(master_fd, o)
            chan.send(
                "pid down, return_code={}, shudown channel...".format(
                    p.returncode
                ).encode()
            )
            chan.shutdown(0)
            t.close()

        except Exception as e:
            logger.error("*** Caught exception: " + str(e.__class__) + ": " + str(e))
            traceback.print_exc()
            try:
                t.close()
            except:
                pass
            sys.exit(1)


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
        rsa_key = paramiko.rsakey.RSAKey.generate(DEFAULT_HOST_RSA_BITS)
        rsa_key.write_private_key_file(str(path))


def load_providers(config):
    return []


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
