from pathlib import Path
import time
import threading


class BaseProvider:
    def __init__(self, provider_name, config, provider_config, data_path):
        self.config = config
        self.provider_name = provider_name
        self.provider_config = provider_config
        self.data_path = Path(data_path)

    def new_server(self, channel):
        """
        Args:
            channel: paramiko channel

        Returns:
            created_server_id: unique id from provision
            created_server_host: server's ip or domain address
        """
        pass

    def destroy_server(self, server_id, server_ip, channel):
        """
        Args:
            channel: Note that the channel can be None.
                     If called from server_killer, channel will be None.
                     if called when user logout from server, channel is active.
        """
        pass

    def ssh_server_command(self, server_id, server_ip):
        """
        Args:
           server_id: the server ssh to, which is returned by you from ``new_server``
           server_ip: ip or domain name.
        Returns:
            list: a command in list format, for later to run exec.
        """
        pass

    def get_bill(self):
        pass

    def send_timepass(self, chan, stop_event):
        start = time.time()

        def _print_time_elaspe():
            while not stop_event.is_set():
                current = time.time()
                chan.send(
                    "\rCreating new server... ({:.1f}s)".format(
                        current - start
                    ).encode()
                )
            chan.send(b"\r\n")

        t = threading.Thread(target=_print_time_elaspe)
        t.start()
