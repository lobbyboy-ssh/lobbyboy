#!/usr/bin/env python

# Copyright (C) 2003-2007  Robey Pointer <robeypointer@gmail.com>
#
# This file is part of paramiko.
#
# Paramiko is free software; you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# Paramiko is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Paramiko; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA.

import base64
from binascii import hexlify
import os
import socket
import sys
import threading
import traceback
import select
import termios
import tty
import pty
import struct
import fcntl
import signal
import errno

import paramiko
from paramiko.py3compat import b, u, decodebytes
from subprocess import Popen, PIPE, STDOUT
from threading import Thread


import termios
import struct
import fcntl


def set_winsize(fd, row, col, xpix=0, ypix=0):
    print("start write using fcntl...")
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    print("write done, col={}, row={}", col, row)


class ChanForwarder(Thread):
    def __init__(self, chan, pipe):
        Thread.__init__(self)
        self.chan = chan
        self.pipe = pipe
        return

    def run(self):
        while 1:
            try:
                data = self.chan.recv(1)
                print("get data from chan... {}".format(data))
                if not data:
                    break
                self.pipe.write(data)
                self.pipe.flush()
                print("copy from chan to pipe... {}".format(data))
            except socket.timeout:
                continue
            except (IOError, socket.error) as e:
                break
        self.pipe.close()
        return


class PipeForwarder(Thread):
    def __init__(self, pipe, chan):
        Thread.__init__(self)
        self.pipe = pipe
        self.chan = chan
        return

    def run(self):
        print("start reading data from pipe...")
        while 1:
            try:
                data = self.pipe.read(1)
                print("get date from pipe: {}".format(data))
                if not data:
                    break
                self.chan.send(data)
            except socket.timeout:
                continue
            except (IOError, socket.error) as e:
                break
        self.pipe.close()
        return


# setup logging
paramiko.util.log_to_file("demo_server.log")

host_key = paramiko.RSAKey(filename="test_rsa.key")
# host_key = paramiko.DSSKey(filename='test_dss.key')

print("Read key: " + u(hexlify(host_key.get_fingerprint())))


class Server(paramiko.ServerInterface):
    # 'data' is the output of base64.b64encode(key)
    # (using the "user_rsa_key" files)
    data = (
        b"AAAAB3NzaC1yc2EAAAABIwAAAIEAyO4it3fHlmGZWJaGrfeHOVY7RWO3P9M7hp"
        b"fAu7jJ2d7eothvfeuoRFtJwhUmZDluRdFyhFY/hFAh76PJKGAusIqIQKlkJxMC"
        b"KDqIexkgHAfID/6mqvmnSJf0b5W8v5h2pI/stOSwTQ+pxVhwJ9ctYDhRSlF0iT"
        b"UWT10hcuO4Ks8="
    )
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


DoGSSAPIKeyExchange = True

# now connect
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
    print("Listening for connection ...")
    client, addr = sock.accept()
except Exception as e:
    print("*** Listen/accept failed: " + str(e))
    traceback.print_exc()
    sys.exit(1)

print("Got a connection!")

try:
    t = paramiko.Transport(client, gss_kex=DoGSSAPIKeyExchange)
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
    chan.send("We are on fire all the time!  Hooray!  Candy corn for everyone!\r\n")
    chan.send("Happy birthday to Robot Dave!\r\n\r\n")

    import time
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
    # command = 'docker run -it --rm centos /bin/bash'.split()

    # open pseudo-terminal to interact with subprocess
    import time

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

    chan_fd = chan.fileno()
    while p.poll() is None:
        print("poll result: {}, pid={}".format(p.poll(), p.pid))
        r, w, e = select.select([master_fd, chan_fd], [], [], 0.1)
        print("read: {}".format(r))
        if master_fd in r:
            d = os.read(master_fd, 10240)
            chan.send(d)
            print("read from master_fd done")
        elif chan_fd in r:
            o = chan.recv(10240)
            os.write(master_fd, o)
            print("read from chan_fd done")
    chan.shutdown(0)

    # while p.poll() is None:
    #     r, w, e = select.select([sys.stdin, master_fd], [], [])
    #     if sys.stdin in r:
    #         d = os.read(sys.stdin.fileno(), 10240)
    #         os.write(master_fd, d)
    #     elif master_fd in r:
    #         o = os.read(master_fd, 10240)
    #         if o:
    #             os.write(sys.stdout.fileno(), o)

except Exception as e:
    print("*** Caught exception: " + str(e.__class__) + ": " + str(e))
    traceback.print_exc()
    try:
        t.close()
    except:
        pass
    sys.exit(1)
