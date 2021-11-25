import base64
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import threading
from binascii import hexlify

import paramiko

from lobbyboy.config import LBConfig
from lobbyboy.exceptions import UnsupportedPrivateKeyTypeException, NoTTYException

logger = logging.getLogger(__name__)


def set_window_size(fd, row, col, xpix=0, ypix=0):
    size = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, size)


class Server(paramiko.ServerInterface):
    def __init__(self, config: LBConfig):
        self.pty_event = threading.Event()
        self.shell_event = threading.Event()
        self.config = config
        self.window_width = self.window_height = 0
        self.proxy_subprocess_pid = None
        self.client_exec = None
        self.client_exec_provider = None
        self.master_fd = self.slave_fd = None

    def check_channel_request(self, kind, channel_id):
        if kind == "session":
            return paramiko.common.OPEN_SUCCEEDED
        return paramiko.common.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        # TODO load config file every time.
        if (username == "foo") and (password == "bar"):
            return paramiko.common.AUTH_SUCCESSFUL
        return paramiko.common.AUTH_FAILED

    @staticmethod
    def _get_key_class(key_type):
        # TODO
        key_cls = {
            "ssh-rsa": paramiko.RSAKey,
            "ssh-dss": paramiko.DSSKey,
            "ssh-ecdsa": paramiko.ECDSAKey,
            "ssh-ed25519": paramiko.Ed25519Key,
        }
        if key_type in key_cls:
            return key_cls[key_type]
        raise UnsupportedPrivateKeyTypeException(f"Unknown key type {key_type}")

    def try_auth(self, key, user, key_str) -> bool:
        key_type = key.get_name().lower()
        key_cls = self._get_key_class(key_type)

        accept_key = key_cls(data=base64.b64decode(key_str))
        k = hexlify(accept_key.get_fingerprint()).decode()
        logger.info(f"try to auth {user} with key {k}")
        success = key == accept_key
        if success:
            logger.info(f"accept auth {user} with key {k}")
        return success

    def check_auth_publickey(self, username: str, key: paramiko.PKey):  # noqa
        use_key_type = key.get_name()
        logger.info(f"try to auth {username} with key type {use_key_type}...")
        config = self.config.reload()
        ssh_key_paris = config.user[username].auth_key_pairs()
        for key_type, key_data in ssh_key_paris:
            if use_key_type != key_type:
                continue
            success = self.try_auth(key, username, key_data)
            if success:
                return paramiko.common.AUTH_SUCCESSFUL
        logger.info(f"Can not auth {username} with any key.")
        return paramiko.common.AUTH_FAILED

    def check_auth_gssapi_with_mic(self, username, gss_authenticated=paramiko.common.AUTH_FAILED, cc_file=None):
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
        if gss_authenticated == paramiko.common.AUTH_SUCCESSFUL:
            return paramiko.common.AUTH_SUCCESSFUL
        return paramiko.common.AUTH_FAILED

    def check_auth_gssapi_keyex(self, username, gss_authenticated=paramiko.common.AUTH_FAILED, cc_file=None):
        # TODO
        if gss_authenticated == paramiko.common.AUTH_SUCCESSFUL:
            logger.info("gss auth success")
            return paramiko.common.AUTH_SUCCESSFUL
        return paramiko.common.AUTH_FAILED

    def enable_auth_gssapi(self):
        return True

    def get_allowed_auths(self, username):
        return "gssapi-keyex,gssapi-with-mic,password,publickey"

    def check_channel_shell_request(self, channel):
        logger.info("client request shell...")
        self.pty_event.wait(timeout=10)
        if not self.pty_event.is_set():
            logger.error("Client never ask a tty, can not allocate shell...")
            raise NoTTYException("No TTY")
        self.shell_event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        logger.info(
            f"Client request pty..., term={term} width={width}, height={height}, "
            f"pixelwidth={pixelwidth}, pixelheight={pixelheight}"
        )
        self.master_fd, self.slave_fd = pty.openpty()
        logger.debug(f"user's pty ready, master_fd={self.master_fd}, slave_fd={self.slave_fd}")

        self.window_width, self.window_height = width, height
        set_window_size(self.master_fd, self.window_height, self.window_width, pixelwidth, pixelheight)
        self.pty_event.set()
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        logger.debug(
            f"client send window size change reuqest... "
            f"width={width}, height={height}, pixelwidth={pixelwidth}, pixelheight={pixelheight}, "
            f"my proxy_subprocess_pid={self.proxy_subprocess_pid}, master_fd={self.master_fd}"
        )
        self.window_width, self.window_height = width, height
        set_window_size(self.master_fd, self.window_height, self.window_width, pixelwidth, pixelheight)

        if self.proxy_subprocess_pid is not None:
            logger.debug(f"send signal to {self.proxy_subprocess_pid}")
            os.kill(self.proxy_subprocess_pid, signal.SIGWINCH)
        return True
