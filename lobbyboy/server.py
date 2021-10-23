#!/usr/bin/env python
import time
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
from binascii import hexlify

import paramiko
from paramiko.py3compat import u, decodebytes
from subprocess import Popen


DoGSSAPIKeyExchange = True


def setup_logs(filename, level=logging.DEBUG):
    """send paramiko logs to a logfile,
    if they're not already going somewhere"""
    frm = "%(levelname)-.3s [%(asctime)s.%(msecs)03d] thr=%(thread)d"
    frm += " %(name)s: %(message)s"
    handler = logging.FileHandler(filename)
    handler.setFormatter(logging.Formatter(frm, "%Y%m%d-%H:%M:%S"))
    logging.basicConfig(level=level, handlers=[handler])


setup_logs("lobbyboy.log")
logger = logging.getLogger(__name__)
logger.info("123")


def set_winsize(fd, row, col, xpix=0, ypix=0):
    print("start write using fcntl...")
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    print("write done, col={}, row={}", col, row)


host_key = paramiko.RSAKey(filename=".ssh/server.key")

print("Read key: " + u(hexlify(host_key.get_fingerprint())))


class Server(paramiko.ServerInterface):
    # 'data' is the output of base64.b64encode(key)
    # (using the "user_rsa_key" files)
    data = (b"AAAAB3NzaC1yc2EAAAADAQABAAABgQC7WY43dCG2GM3wUVRGpACawn1EWAXmnNmj"
            b"oFbtoJCx6qCJW5TRgWCW+CtjqWluE5ripFaj0EQk0C3dJzfFdBlQXwLa1CzUEx48q"
            b"qF/t3OtR21qyLrekWVLcS+FIEllixjhnDe3P+mY2nuywf78fZI9dvLotqOGtk+zjhU"
            b"DX+3wgRbwAjrD4CPRqLVXactB6pdaBX5t1sUhGEjezE7rm0v4At5XxKHRRU9bSGIz"
            b"J+sNmBByavlFXPwSMPLLVuyvFf2OujSUYsXKI6zADu5ypK1dCgsEUoEglQMCaew51NrASZGVsH56Rx1"
            b"vFHssZwksK9WhM8f9CdfRHml4l7JSLea9XQNNovsJKUZ3aaH4DKA8lyhAYeY9/mRD"
            b"iUdfMb6CzyqrXvcb0bDvDX0dzuseP3e6v+7QnrM39zxp5gJXUAIOuEl1Bhrjpa4Lq"
            b"ROK2PLsmHRwnhk5JPlabIuvjVoSnWnFIrwudWgtwg+Zm5phlhjMfxuEglvJwLul9v"
            b"aG4hGfGJ0=")
    good_pub_key = paramiko.RSAKey(data=decodebytes(data))

    def __init__(self):
        self.event = threading.Event()

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        if (username == "robey") and (password == "foo"):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        print("Auth attempt with key: " + u(hexlify(key.get_fingerprint())))
        print(key)
        if (username == "robey") and (key == self.good_pub_key):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_gssapi_with_mic(
        self, username, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None
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
        return paramiko.AUTH_FAILED

    def check_auth_gssapi_keyex(
        self, username, gss_authenticated=paramiko.AUTH_FAILED, cc_file=None
    ):
        if gss_authenticated == paramiko.AUTH_SUCCESSFUL:
            print("gss auth success")
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def enable_auth_gssapi(self):
        return True

    def get_allowed_auths(self, username):
        return "gssapi-keyex,gssapi-with-mic,password,publickey"

    def check_channel_shell_request(self, channel):
        print("request shell...")
        self.event.set()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        print(
            "request pty...",
            channel,
            term,
            width,
            height,
            pixelwidth,
            pixelwidth,
            modes,
        )
        self.master_fd, self.slave_fd = pty.openpty()
        set_winsize(self.master_fd, height, width, pixelwidth, pixelheight)
        return True

    def check_channel_window_change_request(
        self, channel, width, height, pixelwidth, pixelheight
    ):
        print("window change pty...", channel, width, height, pixelwidth, pixelwidth)
        set_winsize(self.master_fd, height, width, pixelwidth, pixelheight)
        import os

        os.kill(self.pid, signal.SIGWINCH)
        return True


class SocketHandlerThread(threading.Thread):
    def __init__(self, socket_client, client_addr) -> None:
        """
        Args:
            socket_client, client_addr: created by socket.accept()
        """
        self.socket_client = socket_client
        self.client_addr = client_addr
        super().__init__()

    def run(self):
        logger.info(
            "start new thread handle {}, addr: {}, my thread id={}".format(
                self.socket_client, self.client_addr, threading.get_ident()
            )
        )
        try:
            t = paramiko.Transport(self.socket_client, gss_kex=DoGSSAPIKeyExchange)
            t.set_gss_host(socket.getfqdn(""))
            try:
                t.load_server_moduli()
            except:
                print("(Failed to load moduli -- gex will be unsupported.)")
                raise
            t.add_server_key(host_key)
            server = Server()
            try:
                t.start_server(server=server)
            except paramiko.SSHException:
                print("*** SSH negotiation failed.")
                sys.exit(1)

            # wait for auth
            chan = t.accept(20)
            if chan is None:
                print("*** No channel.")
                sys.exit(1)
            print("Authenticated!")

            chan.send("\r\n\r\nWelcome to my dorky little BBS!\r\n\r\n")
            chan.send(
                "We are on fire all the time!  Hooray!  Candy corn for everyone!\r\n"
            )
            chan.send("Happy birthday to Robot Dave!\r\n\r\n")

            time.sleep(0.5)
            chan.send("\rhello count 3...")
            time.sleep(0.5)
            chan.send("\rhello count 2...")
            time.sleep(0.5)
            chan.send("\rhello count 1...")

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
            print("*** Caught exception: " + str(e.__class__) + ": " + str(e))
            traceback.print_exc()
            try:
                t.close()
            except:
                pass
            sys.exit(1)


def runserver():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 2200))
    except Exception as e:
        print("*** Bind failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)

    try:
        sock.listen(100)
    except Exception as e:
        print("*** Listen/accept failed: " + str(e))
        traceback.print_exc()
        sys.exit(1)
    while 1:
        logger.info("Listening for connection ...")
        client, addr = sock.accept()
        logger.info("get a connection, from addr: {}".format(addr))
        SocketHandlerThread(client, addr).start()
